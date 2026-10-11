import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import replace

import pytest

from netbalance.config import AppConfig, BackendConfig
from netbalance.metrics import Metrics
from netbalance.protocol import encode_message, read_message
from netbalance.proxy import ProxyServer
from netbalance.registry import Registry


def config_for(port: int, *, max_inflight: int = 10) -> AppConfig:
    return AppConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        http_host="127.0.0.1",
        http_port=0,
        algorithm="rr",
        max_inflight=max_inflight,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.5,
        backend_timeout_s=1.0,
        workload_timeout_s=2.0,
        health_interval_s=0.1,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(BackendConfig("s1", "127.0.0.1", port, 1),),
    )


async def start_backend(
    response: Callable[[dict[str, object]], dict[str, object] | Awaitable[dict[str, object]]]
) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await read_message(reader, 1.0)
            result = response(request)
            if isinstance(result, Awaitable):
                result = await result
            writer.write(encode_message(result))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


async def send(address: tuple[str, int], message: dict[str, object] | bytes) -> dict[str, object]:
    reader, writer = await asyncio.open_connection(*address)
    writer.write(message if isinstance(message, bytes) else encode_message(message))
    await writer.drain()
    response = await read_message(reader, 1.0)
    writer.close()
    await writer.wait_closed()
    return response


async def running_proxy(backend_port: int, *, healthy: bool = True, max_inflight: int = 10):
    config = config_for(backend_port, max_inflight=max_inflight)
    registry = Registry(config.backends, config.algorithm, fail_threshold=2, recover_threshold=2)
    metrics = Metrics(config.max_inflight)
    if healthy:
        await registry.record_probe("s1", success=True)
        await registry.record_probe("s1", success=True)
    proxy = ProxyServer(config, registry, metrics)
    await proxy.start(port=0)
    return proxy, registry, metrics


@pytest.mark.asyncio
async def test_real_socket_round_trip_and_accounting() -> None:
    backend = await start_backend(lambda request: {
        "id": request["id"], "ok": True, "backend_id": "s1", "echo": request["payload"]
    })
    port = backend.sockets[0].getsockname()[1]
    proxy, registry, metrics = await running_proxy(port)
    try:
        response = await send(proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "hello"})
        assert response == {"id": "r1", "ok": True, "backend_id": "s1", "echo": "hello"}
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["totals"]["succeeded"] == 1
        assert snapshot["backends"][0]["active"] == 0
        assert snapshot["backends"][0]["successes"] == 1
    finally:
        await proxy.stop()
        backend.close()
        await backend.wait_closed()


@pytest.mark.asyncio
async def test_no_healthy_backend_and_malformed_client_are_bounded() -> None:
    proxy, registry, metrics = await running_proxy(1, healthy=False)
    try:
        unavailable = await send(proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "x"})
        invalid = await send(proxy.address, b"{bad-json}\n")
        assert unavailable["error"]["code"] == "NO_HEALTHY_BACKEND"
        assert invalid["error"]["code"] == "INVALID_REQUEST"
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["totals"] == {
            "received": 1,
            "succeeded": 0,
            "failed": 1,
            "rejected": 1,
            "protocol_errors": 1,
        }
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_wrong_backend_identity_returns_protocol_error_and_releases() -> None:
    backend = await start_backend(lambda request: {
        "id": request["id"], "ok": True, "backend_id": "wrong", "echo": request["payload"]
    })
    port = backend.sockets[0].getsockname()[1]
    proxy, registry, metrics = await running_proxy(port)
    try:
        response = await send(proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "x"})
        assert response["error"]["code"] == "BACKEND_PROTOCOL_ERROR"
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["inflight"] == 0
        assert snapshot["backends"][0]["active"] == 0
        assert snapshot["backends"][0]["failures"] == 1
    finally:
        await proxy.stop()
        backend.close()
        await backend.wait_closed()


@pytest.mark.asyncio
async def test_backend_refusal_returns_bounded_error_and_releases() -> None:
    unused = await asyncio.start_server(lambda _reader, _writer: None, "127.0.0.1", 0)
    port = unused.sockets[0].getsockname()[1]
    unused.close()
    await unused.wait_closed()
    proxy, registry, metrics = await running_proxy(port)
    try:
        response = await send(proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "x"})
        assert response["error"]["code"] == "BACKEND_UNAVAILABLE"
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["inflight"] == snapshot["backends"][0]["active"] == 0
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_stalled_backend_times_out_and_releases() -> None:
    completed = asyncio.Event()

    async def stall(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await read_message(reader, 1.0)
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            completed.set()

    backend = await asyncio.start_server(stall, "127.0.0.1", 0)
    port = backend.sockets[0].getsockname()[1]
    base = config_for(port)
    config = replace(base, backend_timeout_s=0.05)
    registry = Registry(config.backends, "rr", fail_threshold=2, recover_threshold=2)
    metrics = Metrics(config.max_inflight)
    await registry.record_probe("s1", success=True)
    await registry.record_probe("s1", success=True)
    proxy = ProxyServer(config, registry, metrics)
    await proxy.start(port=0)
    try:
        response = await send(proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "x"})
        assert response["error"]["code"] == "BACKEND_TIMEOUT"
        await asyncio.wait_for(completed.wait(), 1.0)
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["inflight"] == snapshot["backends"][0]["active"] == 0
    finally:
        await proxy.stop()
        backend.close()
        await backend.wait_closed()


@pytest.mark.asyncio
async def test_overload_rejects_second_request_without_second_assignment() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed(request: dict[str, object]) -> dict[str, object]:
        entered.set()
        await release.wait()
        return {"id": request["id"], "ok": True, "backend_id": "s1", "echo": request["payload"]}

    backend = await start_backend(delayed)
    port = backend.sockets[0].getsockname()[1]
    proxy, registry, metrics = await running_proxy(port, max_inflight=1)
    first = asyncio.create_task(send(
        proxy.address, {"id": "r1", "op": "work", "work_units": 1, "payload": "slow"}
    ))
    try:
        await asyncio.wait_for(entered.wait(), 1.0)
        second = await send(proxy.address, {"id": "r2", "op": "work", "work_units": 1, "payload": "fast"})
        assert second["error"]["code"] == "OVERLOADED"
        release.set()
        assert (await first)["ok"] is True
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["totals"]["received"] == 2
        assert snapshot["backends"][0]["assignments"] == 1
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        await proxy.stop()
        backend.close()
        await backend.wait_closed()


@pytest.mark.asyncio
async def test_thirty_requests_cross_proxy_and_three_real_socket_stubs() -> None:
    servers: list[asyncio.Server] = []
    ports: list[int] = []
    for backend_id in ("s1", "s2", "s3"):
        server = await start_backend(lambda request, backend_id=backend_id: {
            "id": request["id"], "ok": True, "backend_id": backend_id, "echo": request["payload"]
        })
        servers.append(server)
        ports.append(server.sockets[0].getsockname()[1])
    base = config_for(ports[0])
    config = replace(
        base,
        backends=tuple(
            BackendConfig(backend_id, "127.0.0.1", port, 1)
            for backend_id, port in zip(("s1", "s2", "s3"), ports, strict=True)
        ),
    )
    registry = Registry(config.backends, "rr", fail_threshold=2, recover_threshold=2)
    metrics = Metrics(config.max_inflight)
    for backend_id in ("s1", "s2", "s3"):
        await registry.record_probe(backend_id, success=True)
        await registry.record_probe(backend_id, success=True)
    proxy = ProxyServer(config, registry, metrics)
    await proxy.start(port=0)
    semaphore = asyncio.Semaphore(6)

    async def request(index: int) -> dict[str, object]:
        async with semaphore:
            return await send(proxy.address, {
                "id": f"r{index:02d}", "op": "work", "work_units": 1, "payload": str(index)
            })

    try:
        responses = await asyncio.gather(*(request(index) for index in range(30)))
        assert all(response["ok"] is True for response in responses)
        assert Counter(response["backend_id"] for response in responses) == {"s1": 10, "s2": 10, "s3": 10}
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["totals"]["succeeded"] == 30
        assert [backend["assignments"] for backend in snapshot["backends"]] == [10, 10, 10]
    finally:
        await proxy.stop()
        for server in servers:
            server.close()
            await server.wait_closed()


@pytest.mark.asyncio
async def test_shutdown_cancels_inflight_work_and_releases_accounting() -> None:
    entered = asyncio.Event()

    async def stall(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await read_message(reader, 1.0)
            entered.set()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    backend = await asyncio.start_server(stall, "127.0.0.1", 0)
    proxy, registry, metrics = await running_proxy(backend.sockets[0].getsockname()[1])
    reader, writer = await asyncio.open_connection(*proxy.address)
    writer.write(encode_message({"id": "r1", "op": "work", "work_units": 1, "payload": "x"}))
    await writer.drain()
    try:
        await asyncio.wait_for(entered.wait(), 1.0)
        await asyncio.wait_for(proxy.stop(), 1.0)
        assert await reader.read() == b""
        snapshot = await metrics.snapshot(await registry.snapshot())
        assert snapshot["inflight"] == snapshot["backends"][0]["active"] == 0
        assert snapshot["totals"]["failed"] == snapshot["backends"][0]["failures"] == 1
        assert not proxy._client_tasks
    finally:
        writer.close()
        await writer.wait_closed()
        await proxy.stop()
        backend.close()
        await backend.wait_closed()
