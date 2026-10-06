"""Validate the shared C0 repository contracts without starting services."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "configs/default.json",
    "docs/contracts.md",
    "docs/metrics.md",
    "docs/protocol.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/fixtures/metrics.json",
)


def load_json(relative_path: str) -> dict:
    with (ROOT / relative_path).open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{relative_path} must contain a JSON object")
    return value


def positive_number(config: dict, key: str) -> None:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"config {key} must be a positive number")


def validate_config(config: dict) -> None:
    expected_ports = {"s1": 9101, "s2": 9102, "s3": 9103}
    if (config.get("listen_host"), config.get("listen_port")) != ("127.0.0.1", 9000):
        raise ValueError("proxy must default to 127.0.0.1:9000")
    if (config.get("http_host"), config.get("http_port")) != ("127.0.0.1", 8000):
        raise ValueError("HTTP service must default to 127.0.0.1:8000")
    if config.get("algorithm") not in {"rr", "lc", "swrr"}:
        raise ValueError("algorithm must be rr, lc, or swrr")
    for key in (
        "max_inflight",
        "client_frame_timeout_s",
        "backend_connect_timeout_s",
        "backend_timeout_s",
        "workload_timeout_s",
        "health_interval_s",
        "health_timeout_s",
        "fail_threshold",
        "recover_threshold",
    ):
        positive_number(config, key)

    backends = config.get("backends")
    if not isinstance(backends, list) or len(backends) != 3:
        raise ValueError("config must contain exactly three backends")
    ids = [backend.get("id") for backend in backends]
    ports = [backend.get("port") for backend in backends]
    if len(set(ids)) != len(ids) or len(set(ports)) != len(ports):
        raise ValueError("backend IDs and ports must be unique")
    if {backend.get("id"): backend.get("port") for backend in backends} != expected_ports:
        raise ValueError("default backend IDs/ports must be s1:9101, s2:9102, s3:9103")
    for backend in backends:
        weight = backend.get("weight")
        if backend.get("host") != "127.0.0.1":
            raise ValueError("default backends must use loopback")
        if isinstance(weight, bool) or not isinstance(weight, int) or not 1 <= weight <= 100:
            raise ValueError("backend weight must be an integer from 1 through 100")


def validate_metrics(metrics: dict) -> None:
    required = {
        "schema_version",
        "metrics_epoch",
        "config_revision",
        "algorithm",
        "inflight",
        "totals",
        "successful_proxy_latency_ms",
        "backends",
        "events",
    }
    if set(metrics) != required or metrics["schema_version"] != 1:
        raise ValueError("metrics fixture does not match schema version 1")
    totals = metrics["totals"]
    if "inflight" in totals:
        raise ValueError("totals must not contain an inflight field")
    if metrics["inflight"] or any(totals.values()):
        raise ValueError("foundation metrics fixture must have zero work accounting")
    backends = metrics["backends"]
    if [backend["id"] for backend in backends] != ["s1", "s2", "s3"]:
        raise ValueError("metrics backends must use stable ID order")
    for backend in backends:
        if backend["health"] != "unknown" or any(
            backend[key] for key in ("active", "assignments", "successes", "failures")
        ):
            raise ValueError("foundation backend metrics must be unknown and zeroed")
    if metrics["events"]:
        raise ValueError("foundation metrics event list must be empty")


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Python 3.12 is required; found {sys.version.split()[0]}")
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError(f"missing required files: {', '.join(missing)}")
    validate_config(load_json("configs/default.json"))
    validate_metrics(load_json("tests/fixtures/metrics.json"))
    import netbalance

    if netbalance.__version__ != "0.1.0":
        raise ValueError("installed netbalance version must be 0.1.0")
    print("C0 foundation verified: Python, package, files, config, and metrics fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
