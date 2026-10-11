import asyncio

import httpx
import pytest

from netbalance.config import AppConfig, BackendConfig
from netbalance.protocol import encode_message, read_message
from netbalance.service import create_app


async def wait_for_health(app, expected: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        async with asyncio.timeout(2.0):
            while (await client.get("/api/health")).json()["backends"][0]["health"] != expected:
                await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_service_lifespan_proxy_round_trip_and_live_api() -> None:
    async def backend_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await read_message(reader, 1.0)
        response = {
            "id": request["id"],
            "ok": True,
            "backend_id": "s1",
            **({"status": "healthy"} if request["op"] == "health" else {"echo": request["payload"]}),
        }
        writer.write(encode_message(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    backend = await asyncio.start_server(backend_handler, "127.0.0.1", 0)
    backend_port = backend.sockets[0].getsockname()[1]
    config = AppConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        http_host="127.0.0.1",
        http_port=0,
        algorithm="rr",
        max_inflight=10,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.5,
        backend_timeout_s=1.0,
        workload_timeout_s=2.0,
        health_interval_s=0.1,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(BackendConfig("s1", "127.0.0.1", backend_port, 1),),
    )
    app = create_app(config)
    try:
        async with app.router.lifespan_context(app):
            await wait_for_health(app, "healthy")
            reader, writer = await asyncio.open_connection(*app.state.proxy.address)
            writer.write(encode_message({"id": "r1", "op": "work", "work_units": 1, "payload": "hello"}))
            await writer.drain()
            response = await read_message(reader, 1.0)
            writer.close()
            await writer.wait_closed()
            assert response == {"id": "r1", "ok": True, "backend_id": "s1", "echo": "hello"}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                metrics = await client.get("/api/metrics")
                current_config = await client.get("/api/config")
                health = await client.get("/api/health")

            assert metrics.status_code == current_config.status_code == health.status_code == 200
            assert metrics.json()["totals"]["succeeded"] == 1
            assert current_config.json()["algorithm"] == "rr"
            assert health.json()["ready"] is True
            assert health.json()["backends"][0]["health"] == "healthy"
            assert app.state.proxy_ready is True
    finally:
        backend.close()
        await backend.wait_closed()
    assert app.state.proxy_ready is False
    with pytest.raises(RuntimeError, match="not running"):
        _ = app.state.proxy.address


@pytest.mark.asyncio
async def test_health_outage_recovery_and_control_endpoints() -> None:
    async def backend_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await read_message(reader, 1.0)
            response = {
                "id": request["id"],
                "ok": True,
                "backend_id": "s1",
                **({"status": "healthy"} if request["op"] == "health" else {"echo": request["payload"]}),
            }
            writer.write(encode_message(response))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    backend = await asyncio.start_server(backend_handler, "127.0.0.1", 0)
    port = backend.sockets[0].getsockname()[1]
    config = AppConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        http_host="127.0.0.1",
        http_port=0,
        algorithm="rr",
        max_inflight=10,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.2,
        backend_timeout_s=0.5,
        workload_timeout_s=1.0,
        health_interval_s=0.05,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(BackendConfig("s1", "127.0.0.1", port, 1),),
    )
    app = create_app(config)
    restarted: asyncio.Server | None = None
    try:
        async with app.router.lifespan_context(app):
            await wait_for_health(app, "healthy")
            snapshot = await app.state.metrics.snapshot(await app.state.registry.snapshot())
            assert snapshot["backends"][0]["assignments"] == 0

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.post("/api/algorithm", json={"algorithm": "lc"})).json() == {
                    "algorithm": "lc", "config_revision": 1
                }
                assert (await client.post("/api/algorithm", json={"algorithm": "random"})).status_code == 422
                assert (await client.post("/api/weights", json={"weights": {}})).status_code == 400
                assert (await client.post("/api/weights", json={"weights": {"s1": True}})).status_code == 422
                assert (await client.post("/api/weights", json={"weights": {"s1": 5}})).json() == {
                    "weights": {"s1": 5}, "config_revision": 2
                }
                assert await app.state.metrics.admit("busy") is True
                busy_reset = await client.post("/api/reset", json={})
                assert busy_reset.status_code == 409
                assert (await client.get("/api/metrics")).json()["metrics_epoch"] == 0
                await app.state.metrics.finish_failure("busy", "BACKEND_UNAVAILABLE")
                assert (await client.post("/api/reset", json={"unexpected": True})).status_code == 422
                assert (await client.post("/api/reset", json={})).json() == {"metrics_epoch": 1}

            backend.close()
            await backend.wait_closed()
            await wait_for_health(app, "unhealthy")
            reader, writer = await asyncio.open_connection(*app.state.proxy.address)
            writer.write(encode_message({"id": "down", "op": "work", "work_units": 1, "payload": "x"}))
            await writer.drain()
            assert (await read_message(reader, 1.0))["error"]["code"] == "NO_HEALTHY_BACKEND"
            writer.close()
            await writer.wait_closed()

            restarted = await asyncio.start_server(backend_handler, "127.0.0.1", port)
            await wait_for_health(app, "healthy")
            final = await app.state.metrics.snapshot(await app.state.registry.snapshot())
            assert final["metrics_epoch"] == 1
            assert [event["outcome"] for event in final["events"] if event["action"] == "health_transition"] == [
                "unhealthy", "healthy"
            ]
    finally:
        backend.close()
        await backend.wait_closed()
        if restarted is not None:
            restarted.close()
            await restarted.wait_closed()
