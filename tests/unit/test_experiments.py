from types import SimpleNamespace

import pytest

from scripts.run_experiments import PROFILES, make_trace, policy_order, summarize, wait_for_reconciled_metrics
from netbalance.workload import AttemptResult, WorkloadSummary


def test_plan_has_four_profiles_and_rotated_policy_order() -> None:
    assert len(PROFILES) == 4
    assert policy_order(1) == ("rr", "lc", "swrr")
    assert policy_order(2) == ("lc", "swrr", "rr")
    assert policy_order(3) == ("swrr", "rr", "lc")


def test_trace_is_reproducible_and_summary_is_reconciled() -> None:
    assert make_trace(42, 5) == make_trace(42, 5)
    assert make_trace(42, 5) != make_trace(43, 5)
    assert len({request["id"] for request in make_trace(42, 5)}) == 5
    results = [
        AttemptResult("r1", "rr", "s1", 1, 0.0, 10.0, True, "s1", None),
        AttemptResult("r2", "rr", "s1", 1, 0.1, 20.0, False, None, "OVERLOADED"),
    ]
    summary = WorkloadSummary(2, 1, 1, 1.0, 1.0, 10.0, 10.0, 10.0, 10.0)
    value = summarize(results, summary, 7)
    assert value["metrics_epoch"] == 7
    assert value["assignments_by_backend"] == {"s1": 1}
    assert value["failures_by_error"] == {"OVERLOADED": 1}


@pytest.mark.asyncio
async def test_metrics_reconciliation_waits_for_proxy_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshots = iter([
        {"metrics_epoch": 7, "inflight": 1, "totals": {"received": 2, "succeeded": 1, "failed": 0}},
        {"metrics_epoch": 7, "inflight": 0, "totals": {"received": 2, "succeeded": 1, "failed": 1}},
    ])
    monkeypatch.setattr("scripts.run_experiments.http_json", lambda *_args: next(snapshots))
    summary = SimpleNamespace(total_attempts=2, successful_attempts=1, failed_attempts=1)
    metrics = await wait_for_reconciled_metrics(8000, 7, summary)
    assert metrics["inflight"] == 0
