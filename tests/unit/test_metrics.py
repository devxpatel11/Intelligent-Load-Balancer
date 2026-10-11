import json
from pathlib import Path

import pytest

from netbalance.config import load_config
from netbalance.metrics import Metrics
from netbalance.registry import Registry


REGISTRY = {"algorithm": "rr", "config_revision": 0, "backends": []}
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_accounting_latency_and_overload_invariants() -> None:
    metrics = Metrics(max_inflight=1)
    assert await metrics.admit("r1") is True
    assert await metrics.admit("r2") is False
    await metrics.assigned("r1", "s1")
    await metrics.finish_success("r1", "s1", 12.5)
    snapshot = await metrics.snapshot(REGISTRY)
    assert snapshot["totals"] == {
        "received": 2,
        "succeeded": 1,
        "failed": 1,
        "rejected": 1,
        "protocol_errors": 0,
    }
    assert snapshot["inflight"] == 0
    assert snapshot["successful_proxy_latency_ms"] == {
        "count": 1,
        "mean": 12.5,
        "p50": 12.5,
        "p95": 12.5,
    }


@pytest.mark.asyncio
async def test_nearest_rank_percentiles_and_protocol_errors() -> None:
    metrics = Metrics(max_inflight=10)
    for index, latency in enumerate(range(1, 21), 1):
        request_id = f"r{index}"
        assert await metrics.admit(request_id)
        await metrics.finish_success(request_id, "s1", float(latency))
    await metrics.protocol_error(None, "INVALID_REQUEST")
    snapshot = await metrics.snapshot(REGISTRY)
    latency = snapshot["successful_proxy_latency_ms"]
    assert latency["p50"] == 10.0
    assert latency["p95"] == 19.0
    assert snapshot["totals"]["protocol_errors"] == 1


@pytest.mark.asyncio
async def test_empty_snapshot_matches_frozen_dashboard_fixture() -> None:
    config = load_config(ROOT / "configs/default.json")
    registry = Registry(
        config.backends,
        config.algorithm,
        fail_threshold=config.fail_threshold,
        recover_threshold=config.recover_threshold,
    )
    snapshot = await Metrics(config.max_inflight).snapshot(await registry.snapshot())
    fixture = json.loads((ROOT / "tests/fixtures/metrics.json").read_text(encoding="utf-8"))
    assert snapshot == fixture
