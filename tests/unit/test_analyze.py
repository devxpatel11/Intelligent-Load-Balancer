import json
from pathlib import Path

import pytest

from netbalance.analyze import analyze, main, read_attempts_from_csv


CSV = """request_id,policy,scenario,repetition,started_offset_s,latency_ms,ok,backend_id,error_code
r1,rr,test,1,0.0,10.0,true,s1,
r2,rr,test,1,0.1,20.0,true,s2,
r3,rr,test,1,0.2,30.0,true,s1,
r4,rr,test,1,0.3,40.0,true,s3,
r5,rr,test,1,0.4,50.0,true,s2,
r6,rr,test,1,0.5,60.0,false,,OVERLOADED
"""


def test_exact_summary_and_reconciliation(tmp_path: Path) -> None:
    csv_path = tmp_path / "run.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    attempts = read_attempts_from_csv(csv_path)
    summary = analyze(attempts, 2.0)
    assert summary["mean_latency_ms"] == 30.0
    assert summary["p50_latency_ms"] == 30.0
    assert summary["p95_latency_ms"] == 50.0
    assert summary["throughput_rps"] == 2.5
    assert summary["assignments_by_backend"] == {"s1": 2, "s2": 2, "s3": 1}
    assert summary["failures_by_error"] == {"OVERLOADED": 1}

    metadata = {"summary": {"total_attempts": 6, "duration_s": 2.0}}
    (tmp_path / "run.csv.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "summary.json"
    assert main([str(csv_path), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["p95_latency_ms"] == 50.0


@pytest.mark.parametrize("text", [
    "request_id,policy\nr1,rr\n",
    CSV.replace("true,s1", "yes,s1", 1),
])
def test_invalid_csv_is_rejected(tmp_path: Path, text: str) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        read_attempts_from_csv(csv_path)


def test_metadata_count_must_match_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "run.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    (tmp_path / "run.csv.meta.json").write_text(
        json.dumps({"summary": {"total_attempts": 5, "duration_s": 2.0}}), encoding="utf-8"
    )
    assert main([str(csv_path)]) == 1
