from scripts.summarize_experiments import aggregate


def test_aggregate_uses_medians_and_reconciles_counts() -> None:
    records = [
        {
            "scenario": "s1", "policy": "rr", "total_attempts": 3,
            "successful_attempts": 3, "failed_attempts": 0,
            "throughput_rps": throughput, "p95_latency_ms": latency,
            "assignments_by_backend": {"s1": 1, "s2": 2}, "failures_by_error": {},
        }
        for throughput, latency in ((10.0, 30.0), (30.0, 10.0), (20.0, 20.0))
    ]
    row = aggregate(records)[0]
    assert row["repetitions"] == 3
    assert row["total_attempts"] == row["successful_attempts"] == 9
    assert row["median_throughput_rps"] == 20.0
    assert row["median_p95_latency_ms"] == 20.0
    assert row["assignments_by_backend"] == {"s1": 3, "s2": 6}
