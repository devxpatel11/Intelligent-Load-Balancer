import csv
import json
from pathlib import Path

import pytest

from scripts.audit_evidence import ARTIFACTS, RAW_COLUMNS, audit


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _evidence(tmp_path: Path) -> tuple[Path, set[tuple[str, str, int]]]:
    root = tmp_path / "experiments"
    run_root = root / "scenario" / "rr" / "1"
    run_root.mkdir(parents=True)
    summary = {
        "total_attempts": 1,
        "successful_attempts": 1,
        "failed_attempts": 0,
        "metrics_epoch": 2,
        "assignments_by_backend": {"s1": 1},
        "failures_by_error": {},
    }
    _write_json(root / "index.json", {
        "git_commit": "abc123",
        "run_count": 1,
        "runs": [{"scenario": "scenario", "policy": "rr", "repetition": 1, **summary}],
    })
    _write_json(run_root / "summary.json", summary)
    _write_json(run_root / "config.json", {"algorithm": "rr"})
    _write_json(run_root / "environment.json", {
        "git_commit": "abc123",
        "inputs": {"scenario": "scenario", "policy": "rr", "repetition": 1},
    })
    _write_json(run_root / "proxy-metrics.json", {
        "algorithm": "rr",
        "metrics_epoch": 2,
        "totals": {"received": 1, "succeeded": 1, "failed": 0},
    })
    (run_root / "trace.json").write_text('{"id":"request-1"}\n', encoding="utf-8")
    with (run_root / "raw.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=sorted(RAW_COLUMNS))
        writer.writeheader()
        writer.writerow({
            "request_id": "request-1", "policy": "rr", "scenario": "scenario", "repetition": "1",
            "started_offset_s": "0", "latency_ms": "1", "ok": "true", "backend_id": "s1", "error_code": "",
        })
    assert all((run_root / name).is_file() for name in ARTIFACTS)
    return root, {("scenario", "rr", 1)}


def test_audit_reconciles_complete_evidence(tmp_path: Path) -> None:
    root, expected = _evidence(tmp_path)
    assert audit(root, expected) == {"runs": 1, "attempts": 1, "files": 7}


def test_audit_rejects_missing_artifact(tmp_path: Path) -> None:
    root, expected = _evidence(tmp_path)
    (root / "scenario" / "rr" / "1" / "trace.json").unlink()
    with pytest.raises(ValueError, match="missing artifacts: trace.json"):
        audit(root, expected)


def test_audit_allows_completion_order_to_differ_from_trace_order(tmp_path: Path) -> None:
    root, expected = _evidence(tmp_path)
    run_root = root / "scenario" / "rr" / "1"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    index["runs"][0].update({"total_attempts": 2, "successful_attempts": 2, "assignments_by_backend": {"s1": 2}})
    index["runs"][0]["failed_attempts"] = 0
    _write_json(root / "index.json", index)
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    summary.update({"total_attempts": 2, "successful_attempts": 2, "assignments_by_backend": {"s1": 2}})
    _write_json(run_root / "summary.json", summary)
    metrics = json.loads((run_root / "proxy-metrics.json").read_text(encoding="utf-8"))
    metrics["totals"].update({"received": 2, "succeeded": 2})
    _write_json(run_root / "proxy-metrics.json", metrics)
    (run_root / "trace.json").write_text('{"id":"request-1"}\n{"id":"request-2"}\n', encoding="utf-8")
    with (run_root / "raw.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=sorted(RAW_COLUMNS))
        writer.writeheader()
        for request_id in ("request-2", "request-1"):
            writer.writerow({
                "request_id": request_id, "policy": "rr", "scenario": "scenario", "repetition": "1",
                "started_offset_s": "0", "latency_ms": "1", "ok": "true", "backend_id": "s1", "error_code": "",
            })
    assert audit(root, expected)["attempts"] == 2
