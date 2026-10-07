"""FastAPI lifecycle and read-only A2 control surface."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from .config import AppConfig, load_config
from .metrics import Metrics
from .proxy import ProxyServer
from .registry import Registry


def create_app(config: AppConfig) -> FastAPI:
    registry = Registry(
        config.backends,
        config.algorithm,
        fail_threshold=config.fail_threshold,
        recover_threshold=config.recover_threshold,
    )
    metrics = Metrics(config.max_inflight)
    proxy = ProxyServer(config, registry, metrics)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await proxy.start()
        app.state.proxy_ready = True
        try:
            yield
        finally:
            app.state.proxy_ready = False
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
