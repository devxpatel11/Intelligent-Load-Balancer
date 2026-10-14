import asyncio
import csv
from collections import Counter
from pathlib import Path

import pytest

from netbalance.backend import BackendServer
from netbalance.config import AppConfig, BackendConfig
from netbalance.protocol import encode_message, read_message
from netbalance.service import create_app
from netbalance.workload import run_workload, write_csv


def make_config(backends: tuple[BackendConfig, ...]) -> AppConfig:
    return AppConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        http_host="127.0.0.1",
        http_port=0,
        algorithm="rr",
        max_inflight=20,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.1,
        backend_timeout_s=0.2,
        workload_timeout_s=1.0,
        health_interval_s=0.02,
        health_timeout_s=0.05,
        fail_threshold=2,
        recover_threshold=2,
        backends=backends,
    )


async def wait_for_health(app, expected: dict[str, str]) -> None:
    async with asyncio.timeout(2.0):
        while True:
            snapshot = await app.state.registry.snapshot()
            actual = {backend["id"]: backend["health"] for backend in snapshot["backends"]}
            if actual == expected:
                return
            await asyncio.sleep(0.01)


async def send(address: tuple[str, int], request_id: str) -> dict[str, object]:
    reader, writer = await asyncio.open_connection(*address)
    writer.write(encode_message({
        "id": request_id,
        "op": "work",
        "work_units": 1,
        "payload": request_id,
    }))
    await writer.drain()
    response = await read_message(reader, 1.0)
    writer.close()
    await writer.wait_closed()
    return response


def assert_accounting(snapshot: dict[str, object]) -> None:
    totals = snapshot["totals"]
    assert totals["received"] == snapshot["inflight"] + totals["succeeded"] + totals["failed"]
    assert totals["rejected"] <= totals["failed"]
    for backend in snapshot["backends"]:
        assert backend["assignments"] == backend["active"] + backend["successes"] + backend["failures"]
        assert backend["active"] >= 0


@pytest.mark.asyncio
async def test_t06_real_backends_workload_and_accounting(tmp_path: Path) -> None:
    servers = [BackendServer(f"s{index}", port=0, service_ms=2) for index in range(1, 4)]
    await asyncio.gather(*(server.start() for server in servers))
    config = make_config(tuple(
        BackendConfig(server.backend_id, "127.0.0.1", server.bound_port, 1)
        for server in servers
    ))
    app = create_app(config)
    try:
        async with app.router.lifespan_context(app):
            await wait_for_health(app, {"s1": "healthy", "s2": "healthy", "s3": "healthy"})
            results, summary = await run_workload(
                *app.state.proxy.address,
                count=30,
                concurrency=6,
                seed=42,
                timeout=1.0,
                policy="rr",
                scenario="a4-integration",
            )
            evidence = tmp_path / "t06-results.csv"
            write_csv(results, evidence)

            assert summary.total_attempts == summary.successful_attempts == 30
            assert summary.failed_attempts == 0
            assert Counter(result.backend_id for result in results) == {"s1": 10, "s2": 10, "s3": 10}
            with evidence.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            assert len(rows) == 30
            assert {row["request_id"] for row in rows} == {f"req-{index:06d}" for index in range(30)}

            snapshot = await app.state.metrics.snapshot(await app.state.registry.snapshot())
            assert snapshot["totals"] == {
                "received": 30,
                "succeeded": 30,
                "failed": 0,
                "rejected": 0,
                "protocol_errors": 0,
            }
            assert snapshot["inflight"] == 0
            assert [backend["assignments"] for backend in snapshot["backends"]] == [10, 10, 10]
            assert [backend["successes"] for backend in snapshot["backends"]] == [10, 10, 10]
            assert_accounting(snapshot)
    finally:
        await asyncio.gather(*(server.stop() for server in servers))
    assert not app.state.proxy._client_tasks
    assert all(server.active_work_count == 0 for server in servers)


@pytest.mark.asyncio
async def test_t07_t08_outage_timeout_recovery_and_accounting() -> None:
    healthy = BackendServer("s1", port=0, service_ms=1)
    await healthy.start()
    healthy_port = healthy.bound_port

    async def hanging_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await read_message(reader, 0.5)
            if request["op"] == "health":
                writer.write(encode_message({
                    "id": request["id"],
                    "ok": True,
                    "backend_id": "s2",
                    "status": "healthy",
                }))
                await writer.drain()
            else:
                await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    hanging = await asyncio.start_server(hanging_handler, "127.0.0.1", 0)
    hanging_port = hanging.sockets[0].getsockname()[1]
    unused = await asyncio.start_server(lambda _reader, _writer: None, "127.0.0.1", 0)
    unused_port = unused.sockets[0].getsockname()[1]
    unused.close()
    await unused.wait_closed()

    config = make_config((
        BackendConfig("s1", "127.0.0.1", healthy_port, 1),
        BackendConfig("s2", "127.0.0.1", hanging_port, 1),
        BackendConfig("s3", "127.0.0.1", unused_port, 1),
    ))
    app = create_app(config)
    restarted: BackendServer | None = None
    try:
        async with app.router.lifespan_context(app):
            await wait_for_health(app, {"s1": "healthy", "s2": "healthy", "s3": "unhealthy"})
            assert (await send(app.state.proxy.address, "success"))["ok"] is True
            timeout_response = await send(app.state.proxy.address, "timeout")
            assert timeout_response["error"]["code"] == "BACKEND_TIMEOUT"

            await healthy.stop()
            hanging.close()
            await hanging.wait_closed()
            await wait_for_health(app, {"s1": "unhealthy", "s2": "unhealthy", "s3": "unhealthy"})
            all_down = await send(app.state.proxy.address, "all-down")
            assert all_down["error"]["code"] == "NO_HEALTHY_BACKEND"

            restarted = BackendServer("s1", port=healthy_port, service_ms=1)
            await restarted.start()
            await wait_for_health(app, {"s1": "healthy", "s2": "unhealthy", "s3": "unhealthy"})
            assert (await send(app.state.proxy.address, "recovered"))["ok"] is True

            snapshot = await app.state.metrics.snapshot(await app.state.registry.snapshot())
            assert snapshot["totals"] == {
                "received": 4,
                "succeeded": 2,
                "failed": 2,
                "rejected": 1,
                "protocol_errors": 0,
            }
            assert snapshot["inflight"] == 0
            assert [backend["assignments"] for backend in snapshot["backends"]] == [2, 1, 0]
            assert [backend["active"] for backend in snapshot["backends"]] == [0, 0, 0]
            assert_accounting(snapshot)
    finally:
        await healthy.stop()
        hanging.close()
        await hanging.wait_closed()
        if restarted is not None:
            await restarted.stop()
    assert not app.state.proxy._client_tasks
