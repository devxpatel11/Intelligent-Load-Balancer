import asyncio

import httpx
import pytest

from netbalance.config import AppConfig, BackendConfig
from netbalance.protocol import encode_message, read_message
from netbalance.service import create_app


@pytest.mark.asyncio
async def test_service_lifespan_proxy_round_trip_and_live_api() -> None:
    async def backend_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await read_message(reader, 1.0)
        writer.write(encode_message({
            "id": request["id"], "ok": True, "backend_id": "s1", "echo": request["payload"]
        }))
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
            await app.state.registry.record_probe("s1", success=True)
            await app.state.registry.record_probe("s1", success=True)
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
