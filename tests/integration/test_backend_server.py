"""Integration tests for BackendServer using real loopback TCP sockets and ephemeral ports."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import sys
import time

import pytest

from netbalance.backend import BackendServer, encode_json_frame


async def read_one_json_response(reader: asyncio.StreamReader) -> dict:
    """Read one newline-delimited JSON response line from the stream."""
    line = await reader.readline()
    if not line:
        raise EOFError("Connection closed before response received")
    return json.loads(line.decode("utf-8"))


async def _run_test_work_request_success() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        req = {"id": "r0001", "op": "work", "work_units": 1, "payload": "hello world"}
        writer.write(encode_json_frame(req))
        await writer.drain()

        resp = await read_one_json_response(reader)
        assert resp["id"] == "r0001"
        assert resp["ok"] is True
        assert resp["backend_id"] == "s1"
        assert resp["echo"] == "hello world"

        # Connection should be closed by the server
        extra = await reader.read()
        assert extra == b""
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_work_request_success() -> None:
    asyncio.run(_run_test_work_request_success())


async def _run_test_health_request_success() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        req = {"id": "probe-1", "op": "health"}
        writer.write(encode_json_frame(req))
        await writer.drain()

        resp = await read_one_json_response(reader)
        assert resp["id"] == "probe-1"
        assert resp["ok"] is True
        assert resp["backend_id"] == "s1"
        assert resp["status"] == "healthy"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_health_request_success() -> None:
    asyncio.run(_run_test_health_request_success())


class SynchronizedBackendServer(BackendServer):
    """Subclass allowing deterministic synchronization hooks for concurrency testing."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.work_entered_events: list[asyncio.Event] = []
        self.work_release_event = asyncio.Event()

    async def _process_work(self, work_units: int) -> None:
        entered = asyncio.Event()
        self.work_entered_events.append(entered)
        async with self._work_semaphore:
            entered.set()
            await self.work_release_event.wait()


async def _run_test_t05_synchronized_concurrency_and_health_bypass() -> None:
    """Deterministic, synchronization-based concurrency and health responsiveness test (T05)."""
    server = SynchronizedBackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=0.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port

        # Connect work request 1
        r1, w1 = await asyncio.open_connection("127.0.0.1", port)
        w1.write(encode_json_frame({"id": "w1", "op": "work", "work_units": 1, "payload": "task1"}))
        await w1.drain()

        # Connect work request 2
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        w2.write(encode_json_frame({"id": "w2", "op": "work", "work_units": 1, "payload": "task2"}))
        await w2.drain()

        # Wait until both work tasks have entered work and acquired the 2 capacity slots
        while len(server.work_entered_events) < 2:
            await asyncio.sleep(0.01)
        await server.work_entered_events[0].wait()
        await server.work_entered_events[1].wait()

        # Both capacity slots must be occupied
        assert server.active_work_count == 2

        # Connect health probe: must bypass work semaphore and return immediately
        hr, hw = await asyncio.open_connection("127.0.0.1", port)
        hw.write(encode_json_frame({"id": "probe-sync", "op": "health"}))
        await hw.drain()

        # Response arrives despite work capacity being 100% saturated
        health_resp = await asyncio.wait_for(read_one_json_response(hr), timeout=1.0)
        assert health_resp["id"] == "probe-sync"
        assert health_resp["status"] == "healthy"
        hw.close()
        await hw.wait_closed()

        # Release the synchronized work tasks
        server.work_release_event.set()

        resp1 = await asyncio.wait_for(read_one_json_response(r1), timeout=1.0)
        resp2 = await asyncio.wait_for(read_one_json_response(r2), timeout=1.0)
        assert resp1["ok"] is True and resp1["id"] == "w1"
        assert resp2["ok"] is True and resp2["id"] == "w2"

        w1.close()
        w2.close()
        await w1.wait_closed()
        await w2.wait_closed()
    finally:
        await server.stop()


def test_t05_synchronized_concurrency_and_health_bypass() -> None:
    asyncio.run(_run_test_t05_synchronized_concurrency_and_health_bypass())


async def _run_test_client_disconnect_resilience() -> None:
    """Verify client abruptly disconnecting does not crash listener or affect subsequent requests."""
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=100.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port

        # Connect and immediately close socket without reading response
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", port))
        s.sendall(b'{"id":"disc-1","op":"work","work_units":2,"payload":"foo"}\n')
        s.close()  # Hard abrupt close

        # Connect another socket with partial frame, then close
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.connect(("127.0.0.1", port))
        s2.sendall(b'{"id":"disc-2"')
        s2.close()

        await asyncio.sleep(0.05)

        # Server listener must remain healthy and responsive
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(encode_json_frame({"id": "health-after-disconnect", "op": "health"}))
        await w.drain()
        resp = await read_one_json_response(r)
        assert resp["id"] == "health-after-disconnect"
        assert resp["status"] == "healthy"
        w.close()
        await w.wait_closed()
    finally:
        await server.stop()


def test_client_disconnect_resilience() -> None:
    asyncio.run(_run_test_client_disconnect_resilience())


async def _run_test_server_shutdown_frees_port_and_sockets() -> None:
    """Verify stop() terminates tasks, closes sockets, and frees listening port for immediate reuse."""
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=500.0,
        capacity=2,
    )
    await server.start()
    port = server.bound_port

    # Open connection and start long request
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(encode_json_frame({"id": "shutdown-req", "op": "work", "work_units": 5, "payload": "delay"}))
    await w.drain()

    # Give it a moment to begin processing
    await asyncio.sleep(0.02)
    assert len(server._active_tasks) > 0

    # Stop server
    await server.stop()

    assert server._server is None
    assert len(server._active_tasks) == 0
    w.close()
    await w.wait_closed()

    # Verify port is free to be rebound immediately
    rebound_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    rebound_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rebound_sock.bind(("127.0.0.1", port))
    finally:
        rebound_sock.close()


def test_server_shutdown_frees_port_and_sockets() -> None:
    asyncio.run(_run_test_server_shutdown_frees_port_and_sockets())


async def _run_test_t04_split_frame_handling() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        full_frame = encode_json_frame({"id": "split-1", "op": "work", "work_units": 1, "payload": "part1_part2"})

        chunk1 = full_frame[:10]
        chunk2 = full_frame[10:25]
        chunk3 = full_frame[25:]

        writer.write(chunk1)
        await writer.drain()
        await asyncio.sleep(0.02)

        writer.write(chunk2)
        await writer.drain()
        await asyncio.sleep(0.02)

        writer.write(chunk3)
        await writer.drain()

        resp = await read_one_json_response(reader)
        assert resp["id"] == "split-1"
        assert resp["ok"] is True
        assert resp["echo"] == "part1_part2"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_t04_split_frame_handling() -> None:
    asyncio.run(_run_test_t04_split_frame_handling())


async def _run_test_t04_oversized_frame_rejection() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        oversized_data = b"x" * 65537 + b"\n"
        writer.write(oversized_data)
        await writer.drain()

        resp = await read_one_json_response(reader)
        assert resp["ok"] is False
        assert resp["error"]["code"] == "FRAME_TOO_LARGE"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_t04_oversized_frame_rejection() -> None:
    asyncio.run(_run_test_t04_oversized_frame_rejection())


async def _run_test_t04_malformed_json_rejection() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        writer.write(b'{"id":"bad-json", "op": "work", unquoted_key}\n')
        await writer.drain()

        resp = await read_one_json_response(reader)
        assert resp["ok"] is False
        assert resp["error"]["code"] == "INVALID_REQUEST"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_t04_malformed_json_rejection() -> None:
    asyncio.run(_run_test_t04_malformed_json_rejection())


async def _run_test_t04_eof_before_newline() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        writer.write(b'{"id":"incomplete"')
        await writer.drain()
        writer.write_eof()

        try:
            resp = await read_one_json_response(reader)
            assert resp["ok"] is False
            assert resp["error"]["code"] == "INVALID_REQUEST"
        except EOFError:
            pass

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_t04_eof_before_newline() -> None:
    asyncio.run(_run_test_t04_eof_before_newline())


async def _run_test_t04_client_read_timeout() -> None:
    server = BackendServer(
        backend_id="s1",
        host="127.0.0.1",
        port=0,
        service_ms=50.0,
        capacity=2,
    )
    await server.start()
    try:
        port = server.bound_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        t0 = time.perf_counter()
        resp = await asyncio.wait_for(read_one_json_response(reader), timeout=3.0)
        elapsed = time.perf_counter() - t0

        assert 1.8 <= elapsed <= 2.5
        assert resp["ok"] is False
        assert resp["error"]["code"] == "CLIENT_READ_TIMEOUT"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_t04_client_read_timeout() -> None:
    asyncio.run(_run_test_t04_client_read_timeout())


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_cli_subprocess_lifecycle() -> None:
    """Test running python -m netbalance.backend as an independent subprocess."""
    port = get_free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "netbalance.backend",
            "--id",
            "s_proc",
            "--port",
            str(port),
            "--service-ms",
            "20",
            "--capacity",
            "3",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        ready = False
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2) as s:
                    s.sendall(b'{"id":"p1","op":"health"}\n')
                    data = s.recv(1024)
                    resp = json.loads(data.decode("utf-8"))
                    assert resp["id"] == "p1"
                    assert resp["status"] == "healthy"
                    assert resp["backend_id"] == "s_proc"
                    ready = True
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.05)

        assert ready, "Subprocess backend did not become ready"

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
