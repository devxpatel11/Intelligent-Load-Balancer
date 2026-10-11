"""Unit tests for the workload client engine and CSV accounting."""

from __future__ import annotations

import asyncio
import io
import math
import tempfile
from pathlib import Path

import pytest

from netbalance.protocol import encode_message
from netbalance.workload import (
    AttemptResult,
    WorkloadSummary,
    calculate_percentile,
    compute_summary,
    execute_single_attempt,
    run_workload,
    write_csv,
)


def test_percentile_calculation() -> None:
    # Nearest rank: ceil(q * N) - 1
    # For N=10, sorted 1..10:
    # q=0.5 -> ceil(5) - 1 = 4 -> index 4 is 5
    # q=0.95 -> ceil(9.5) - 1 = 9 -> index 9 is 10
    values = [float(i) for i in range(1, 11)]
    assert calculate_percentile(values, 0.50) == 5.0
    assert calculate_percentile(values, 0.95) == 10.0
    assert calculate_percentile([], 0.50) is None


def test_zero_success_summary() -> None:
    results = [
        AttemptResult(
            request_id="r1",
            policy="rr",
            scenario="fail_test",
            repetition=1,
            started_offset_s=0.01,
            latency_ms=10.0,
            ok=False,
            backend_id=None,
            error_code="CONNECTION_ERROR",
        ),
        AttemptResult(
            request_id="r2",
            policy="rr",
            scenario="fail_test",
            repetition=1,
            started_offset_s=0.02,
            latency_ms=12.0,
            ok=False,
            backend_id=None,
            error_code="TIMEOUT",
        ),
    ]
    summary = compute_summary(results, duration_s=1.5)
    assert summary.total_attempts == 2
    assert summary.successful_attempts == 0
    assert summary.failed_attempts == 2
    assert summary.throughput_rps == 0.0
    assert summary.mean_latency_ms is None
    assert summary.p50_latency_ms is None
    assert summary.p95_latency_ms is None
    assert summary.p99_latency_ms is None


def test_csv_columns_and_all_attempts_written() -> None:
    results = [
        AttemptResult(
            request_id="r1",
            policy="rr",
            scenario="default",
            repetition=1,
            started_offset_s=0.005,
            latency_ms=25.5,
            ok=True,
            backend_id="s1",
            error_code=None,
        ),
        AttemptResult(
            request_id="r2",
            policy="rr",
            scenario="default",
            repetition=1,
            started_offset_s=0.015,
            latency_ms=15.2,
            ok=False,
            backend_id=None,
            error_code="OVERLOADED",
        ),
    ]
    buf = io.StringIO()
    write_csv(results, buf)
    csv_text = buf.getvalue().strip().split("\r\n" if "\r\n" in buf.getvalue() else "\n")

    assert csv_text[0] == "request_id,policy,scenario,repetition,started_offset_s,latency_ms,ok,backend_id,error_code"
    assert len(csv_text) == 3
    assert "r1,rr,default,1,0.005000,25.500,true,s1," in csv_text[1]
    assert "r2,rr,default,1,0.015000,15.200,false,,OVERLOADED" in csv_text[2]


@pytest.mark.asyncio
async def test_attempt_request_id_mismatch() -> None:
    async def mock_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        # Return wrong request id
        writer.write(encode_message({"id": "wrong-id", "ok": True, "backend_id": "s1", "echo": "test"}))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(mock_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        req = {"id": "req-1", "op": "work", "work_units": 1, "payload": "test"}
        res = await execute_single_attempt(
            "127.0.0.1", port, req, timeout_s=1.0, policy="rr", scenario="test", repetition=1, started_offset_s=0.0
        )
        assert res.ok is False
        assert res.error_code == "REQUEST_ID_MISMATCH"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_attempt_malformed_response() -> None:
    async def mock_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        # Missing echo or backend_id on ok=True
        writer.write(b"not json at all\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(mock_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        req = {"id": "req-1", "op": "work", "work_units": 1, "payload": "test"}
        res = await execute_single_attempt(
            "127.0.0.1", port, req, timeout_s=1.0, policy="rr", scenario="test", repetition=1, started_offset_s=0.0
        )
        assert res.ok is False
        assert res.error_code == "MALFORMED_RESPONSE"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_attempt_timeout_categorization() -> None:
    async def stall_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        await asyncio.sleep(0.5)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(stall_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        req = {"id": "req-1", "op": "work", "work_units": 1, "payload": "test"}
        res = await execute_single_attempt(
            "127.0.0.1", port, req, timeout_s=0.05, policy="rr", scenario="test", repetition=1, started_offset_s=0.0
        )
        assert res.ok is False
        assert res.error_code == "TIMEOUT"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_attempt_connection_refused() -> None:
    # Port 1 on loopback is rejected by the OS network stack within 2.0s on Windows
    req = {"id": "req-1", "op": "work", "work_units": 1, "payload": "test"}
    res = await execute_single_attempt(
        "127.0.0.1", 1, req, timeout_s=3.0, policy="rr", scenario="test", repetition=1, started_offset_s=0.0
    )
    assert res.ok is False
    assert res.error_code == "CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_bounded_concurrency_in_run_workload() -> None:
    active_connections = 0
    max_observed_concurrency = 0
    lock = asyncio.Lock()

    async def tracking_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal active_connections, max_observed_concurrency
        async with lock:
            active_connections += 1
            if active_connections > max_observed_concurrency:
                max_observed_concurrency = active_connections
        line = await reader.readline()
        await asyncio.sleep(0.02)
        import json
        req = json.loads(line.decode("utf-8"))
        writer.write(encode_message({"id": req["id"], "ok": True, "backend_id": "s1", "echo": req["payload"]}))
        await writer.drain()
        async with lock:
            active_connections -= 1
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(tracking_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        results, summary = await run_workload(
            host="127.0.0.1",
            port=port,
            count=20,
            concurrency=3,
            seed=123,
            timeout=2.0,
        )
        assert len(results) == 20
        assert summary.successful_attempts == 20
        assert summary.failed_attempts == 0
        assert max_observed_concurrency <= 3
    finally:
        server.close()
        await server.wait_closed()
