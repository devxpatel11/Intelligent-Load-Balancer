"""FastAPI lifecycle and read-only A2 control surface."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .config import AppConfig, load_config
from .metrics import Metrics
from .protocol import MAX_FRAME_BYTES, ProtocolError, encode_message, read_message
from .proxy import ProxyServer
from .registry import Registry


class _RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlgorithmUpdate(_RequestBody):
    algorithm: Literal["rr", "lc", "swrr"]


class WeightsUpdate(_RequestBody):
    weights: dict[str, Annotated[StrictInt, Field(ge=1, le=100)]]


class ResetRequest(_RequestBody):
    pass


async def _probe(config: AppConfig, backend_id: str, host: str, port: int) -> bool:
    writer: asyncio.StreamWriter | None = None
    request_id = f"probe-{backend_id}"
    try:
        async with asyncio.timeout(config.health_timeout_s):
            reader, writer = await asyncio.open_connection(host, port, limit=MAX_FRAME_BYTES)
            writer.write(encode_message({"id": request_id, "op": "health"}))
            await writer.drain()
            response = await read_message(reader, config.health_timeout_s)
            return response == {
                "id": request_id,
                "ok": True,
                "backend_id": backend_id,
                "status": "healthy",
            }
    except (TimeoutError, ConnectionError, OSError, ProtocolError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), config.health_timeout_s)
            except (TimeoutError, ConnectionError, OSError):
                pass


async def _health_loop(config: AppConfig, registry: Registry, metrics: Metrics) -> None:
    while True:
        results = await asyncio.gather(*(
            _probe(config, backend.id, backend.host, backend.port) for backend in config.backends
        ))
        for backend, success in zip(config.backends, results, strict=True):
            if await registry.record_probe(backend.id, success=success):
                await metrics.health_transition(backend.id, "healthy" if success else "unhealthy")
        await asyncio.sleep(config.health_interval_s)


def create_app(config: AppConfig) -> FastAPI:
    registry = Registry(
        config.backends,
        config.algorithm,
        fail_threshold=config.fail_threshold,
        recover_threshold=config.recover_threshold,
    )
    metrics = Metrics(config.max_inflight)
    proxy = ProxyServer(config, registry, metrics)
    health_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal health_task
        await proxy.start()
        health_task = asyncio.create_task(_health_loop(config, registry, metrics))
        app.state.proxy_ready = True
        try:
            yield
        finally:
            app.state.proxy_ready = False
            if health_task is not None:
                health_task.cancel()
                await asyncio.gather(health_task, return_exceptions=True)
                health_task = None
            await proxy.stop()

    app = FastAPI(title="NetBalance", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.registry = registry
    app.state.metrics = metrics
    app.state.proxy = proxy
    app.state.proxy_ready = False

    @app.get("/api/metrics")
    async def get_metrics() -> dict[str, object]:
        return await metrics.snapshot(await registry.snapshot())

    @app.get("/api/config")
    async def get_config() -> dict[str, object]:
        snapshot = asdict(config)
        registry_snapshot = await registry.snapshot()
        snapshot["algorithm"] = registry_snapshot["algorithm"]
        snapshot["config_revision"] = registry_snapshot["config_revision"]
        snapshot["backends"] = [
            {key: backend[key] for key in ("id", "host", "port", "weight")}
            for backend in registry_snapshot["backends"]
        ]
        return snapshot

    @app.get("/api/health")
    async def get_health() -> dict[str, object]:
        snapshot = await registry.snapshot()
        return {
            "ready": app.state.proxy_ready,
            "backends": [
                {
                    "id": backend["id"],
                    "health": backend["health"],
                    "consecutive_probe_successes": backend["consecutive_probe_successes"],
                    "consecutive_probe_failures": backend["consecutive_probe_failures"],
                    "last_transition_at": backend["last_transition_at"],
                }
                for backend in snapshot["backends"]
            ],
        }

    @app.post("/api/algorithm")
    async def set_algorithm(update: AlgorithmUpdate) -> dict[str, object]:
        revision = await registry.set_algorithm(update.algorithm)
        await metrics.config_change()
        return {"algorithm": update.algorithm, "config_revision": revision}

    @app.post("/api/weights")
    async def set_weights(update: WeightsUpdate) -> dict[str, object]:
        try:
            revision = await registry.set_weights(update.weights)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await metrics.config_change()
        return {"weights": update.weights, "config_revision": revision}

    @app.post("/api/reset")
    async def reset_metrics(_request: ResetRequest) -> dict[str, int]:
        try:
            epoch = await metrics.reset(registry)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"metrics_epoch": epoch}

    web_root = Path(__file__).resolve().parents[2] / "web"

    @app.get("/", include_in_schema=False)
    async def dashboard() -> RedirectResponse:
        return RedirectResponse("/web/")

    app.mount("/web", StaticFiles(directory=web_root, html=True), name="web")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NetBalance proxy and HTTP API")
    parser.add_argument("--config", type=Path, default=Path("configs/default.json"))
    parser.add_argument("--http-port", type=int)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.http_port is not None:
        config = config.with_http_port(args.http_port)
    uvicorn.run(create_app(config), host=config.http_host, port=config.http_port, workers=1)


if __name__ == "__main__":
    main()
