"""Validated application configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path


def _integer(value: object, name: str, minimum: int, maximum: int = 65_535) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


@dataclass(frozen=True, slots=True)
class BackendConfig:
    id: str
    host: str
    port: int
    weight: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    listen_host: str
    listen_port: int
    http_host: str
    http_port: int
    algorithm: str
    max_inflight: int
    client_frame_timeout_s: float
    backend_connect_timeout_s: float
    backend_timeout_s: float
    workload_timeout_s: float
    health_interval_s: float
    health_timeout_s: float
    fail_threshold: int
    recover_threshold: int
    backends: tuple[BackendConfig, ...]

    def with_http_port(self, port: int) -> AppConfig:
        return replace(self, http_port=_integer(port, "http_port", 0))


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open(encoding="utf-8") as source:
        raw = json.load(source)
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a JSON object")
    backend_rows = raw.get("backends")
    if not isinstance(backend_rows, list) or not backend_rows:
        raise ValueError("backends must be a nonempty list")
    backends: list[BackendConfig] = []
    for index, row in enumerate(backend_rows):
        if not isinstance(row, dict):
            raise ValueError(f"backends[{index}] must be an object")
        backend_id = row.get("id")
        host = row.get("host")
        if not isinstance(backend_id, str) or not backend_id:
            raise ValueError(f"backends[{index}].id must be a nonempty string")
        if not isinstance(host, str) or not host:
            raise ValueError(f"backends[{index}].host must be a nonempty string")
        backends.append(BackendConfig(
            id=backend_id,
            host=host,
            port=_integer(row.get("port"), f"backends[{index}].port", 1),
            weight=_integer(row.get("weight"), f"backends[{index}].weight", 1, 100),
        ))
    if len({backend.id for backend in backends}) != len(backends):
        raise ValueError("backend IDs must be unique")
    if len({backend.port for backend in backends}) != len(backends):
        raise ValueError("backend ports must be unique")
    algorithm = raw.get("algorithm")
    if algorithm not in {"rr", "lc", "swrr"}:
        raise ValueError("algorithm must be rr, lc, or swrr")
    return AppConfig(
        listen_host=_nonempty_string(raw.get("listen_host"), "listen_host"),
        listen_port=_integer(raw.get("listen_port"), "listen_port", 1),
        http_host=_nonempty_string(raw.get("http_host"), "http_host"),
        http_port=_integer(raw.get("http_port"), "http_port", 1),
        algorithm=algorithm,
        max_inflight=_integer(raw.get("max_inflight"), "max_inflight", 1),
        client_frame_timeout_s=_positive_number(raw.get("client_frame_timeout_s"), "client_frame_timeout_s"),
        backend_connect_timeout_s=_positive_number(raw.get("backend_connect_timeout_s"), "backend_connect_timeout_s"),
        backend_timeout_s=_positive_number(raw.get("backend_timeout_s"), "backend_timeout_s"),
        workload_timeout_s=_positive_number(raw.get("workload_timeout_s"), "workload_timeout_s"),
        health_interval_s=_positive_number(raw.get("health_interval_s"), "health_interval_s"),
        health_timeout_s=_positive_number(raw.get("health_timeout_s"), "health_timeout_s"),
        fail_threshold=_integer(raw.get("fail_threshold"), "fail_threshold", 1),
        recover_threshold=_integer(raw.get("recover_threshold"), "recover_threshold", 1),
        backends=tuple(backends),
    )
