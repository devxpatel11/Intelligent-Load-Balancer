"""Validate the committed B5 experiment evidence without regenerating it."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ARTIFACTS = (
    "raw.csv",
    "summary.json",
    "config.json",
    "environment.json",
    "trace.json",
    "proxy-metrics.json",
)
RAW_COLUMNS = {
    "request_id",
    "policy",
    "scenario",
    "repetition",
    "started_offset_s",
    "latency_ms",
    "ok",
    "backend_id",
    "error_code",
}
SCENARIOS = ("s1-uniform-c1", "s1-uniform-c30", "s2-slow-c30", "s3-capacity-c30")
POLICIES = ("rr", "lc", "swrr")
REPETITIONS = (1, 2, 3)
EXPECTED_RUNS = {
    (scenario, policy, repetition)
    for scenario in SCENARIOS
    for policy in POLICIES
    for repetition in REPETITIONS
}


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def audit(root: Path, expected_runs: set[tuple[str, str, int]] | None = None) -> dict[str, int]:
    index = _load_json(root / "index.json")
    runs = index.get("runs")
    _require(isinstance(runs, list), "index.json runs must be a list")
    _require(index.get("run_count") == len(runs), "index run_count does not match runs")

    seen: set[tuple[str, str, int]] = set()
    attempts = 0
    files = 1
    for run in runs:
        _require(isinstance(run, dict), "each indexed run must be an object")
        scenario = str(run["scenario"])
        policy = str(run["policy"])
        repetition = int(run["repetition"])
        key = (scenario, policy, repetition)
        _require(key not in seen, f"duplicate run: {key}")
        seen.add(key)

        run_root = root / scenario / policy / str(repetition)
        missing = [name for name in ARTIFACTS if not (run_root / name).is_file()]
        _require(not missing, f"{key} missing artifacts: {', '.join(missing)}")
        files += len(ARTIFACTS)

        summary = _load_json(run_root / "summary.json")
        for field, value in summary.items():
            _require(run.get(field) == value, f"{key} summary mismatch for {field}")

        with (run_root / "raw.csv").open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            _require(reader.fieldnames is not None and RAW_COLUMNS <= set(reader.fieldnames), f"{key} raw columns are incomplete")
            rows = list(reader)
        total = int(run["total_attempts"])
        successful = int(run["successful_attempts"])
        failed = int(run["failed_attempts"])
        _require(len(rows) == total, f"{key} raw row count mismatch")
        _require(successful + failed == total, f"{key} success/failure counts do not reconcile")
        _require(sum(row["ok"] == "true" for row in rows) == successful, f"{key} raw success count mismatch")
        _require(sum(row["ok"] == "false" for row in rows) == failed, f"{key} raw failure count mismatch")
        _require(all(row["policy"] == policy and row["scenario"] == scenario for row in rows), f"{key} raw labels mismatch")
        _require(all(int(row["repetition"]) == repetition for row in rows), f"{key} raw repetition mismatch")

        assignments = Counter(row["backend_id"] for row in rows if row["ok"] == "true" and row["backend_id"])
        failures = Counter(row["error_code"] for row in rows if row["error_code"])
        _require(dict(sorted(assignments.items())) == run["assignments_by_backend"], f"{key} assignments mismatch")
        _require(dict(sorted(failures.items())) == run["failures_by_error"], f"{key} failures mismatch")

        trace = [json.loads(line) for line in (run_root / "trace.json").read_text(encoding="utf-8").splitlines()]
        _require(len(trace) == total, f"{key} trace length mismatch")
        trace_ids = Counter(item["id"] for item in trace)
        raw_ids = Counter(row["request_id"] for row in rows)
        _require(trace_ids == raw_ids and all(count == 1 for count in trace_ids.values()), f"{key} trace IDs mismatch")

        config = _load_json(run_root / "config.json")
        environment = _load_json(run_root / "environment.json")
        inputs = environment.get("inputs")
        _require(config.get("algorithm") == policy, f"{key} config policy mismatch")
        _require(environment.get("git_commit") == index.get("git_commit"), f"{key} commit mismatch")
        _require(isinstance(inputs, dict), f"{key} environment inputs are missing")
        _require(inputs.get("scenario") == scenario and inputs.get("policy") == policy, f"{key} environment labels mismatch")
        _require(inputs.get("repetition") == repetition, f"{key} environment repetition mismatch")

        metrics = _load_json(run_root / "proxy-metrics.json")
        totals = metrics.get("totals")
        _require(metrics.get("algorithm") == policy, f"{key} proxy policy mismatch")
        _require(metrics.get("metrics_epoch") == run["metrics_epoch"], f"{key} metrics epoch mismatch")
        _require(isinstance(totals, dict), f"{key} proxy totals are missing")
        _require(totals.get("received") == total, f"{key} proxy received count mismatch")
        _require(totals.get("succeeded") == successful and totals.get("failed") == failed, f"{key} client/proxy totals mismatch")
        attempts += total

    if expected_runs is not None:
        _require(seen == expected_runs, "indexed runs do not match the required experiment matrix")
    return {"runs": len(runs), "attempts": attempts, "files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit committed B5 experiment evidence")
    parser.add_argument("root", type=Path, nargs="?", default=Path("results/experiments"))
    args = parser.parse_args(argv)
    result = audit(args.root, EXPECTED_RUNS)
    print(f"Evidence audit passed: {result['runs']} runs, {result['attempts']} attempts, {result['files']} indexed files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
