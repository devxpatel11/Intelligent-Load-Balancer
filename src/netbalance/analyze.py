"""Reconcile a benchmark CSV with its metadata and report exact statistics."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .workload import AttemptResult, CSV_COLUMNS, compute_summary


def read_attempts_from_csv(csv_path: Path) -> list[AttemptResult]:
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError(f"CSV columns must be {CSV_COLUMNS}")
        attempts = []
        for line_number, row in enumerate(reader, start=2):
            try:
                if row["ok"] not in {"true", "false"}:
                    raise ValueError("ok must be true or false")
                attempt = AttemptResult(
                    request_id=row["request_id"],
                    policy=row["policy"],
                    scenario=row["scenario"],
                    repetition=int(row["repetition"]),
                    started_offset_s=float(row["started_offset_s"]),
                    latency_ms=float(row["latency_ms"]),
                    ok=row["ok"] == "true",
                    backend_id=row["backend_id"] or None,
                    error_code=row["error_code"] or None,
                )
                if not attempt.request_id or not attempt.policy or not attempt.scenario:
                    raise ValueError("request_id, policy, and scenario must be nonempty")
                if attempt.repetition < 1 or attempt.started_offset_s < 0 or attempt.latency_ms < 0:
                    raise ValueError("repetition must be positive and timings must be nonnegative")
                if not math.isfinite(attempt.started_offset_s) or not math.isfinite(attempt.latency_ms):
                    raise ValueError("timings must be finite")
                if attempt.ok and not attempt.backend_id:
                    raise ValueError("successful rows require backend_id")
                if not attempt.ok and not attempt.error_code:
                    raise ValueError("failed rows require error_code")
                attempts.append(attempt)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid CSV row {line_number}: {exc}") from exc
    return attempts


def analyze(attempts: list[AttemptResult], duration_s: float) -> dict[str, object]:
    summary = asdict(compute_summary(attempts, duration_s))
    summary["assignments_by_backend"] = dict(sorted(Counter(
        attempt.backend_id for attempt in attempts if attempt.ok and attempt.backend_id
    ).items()))
    summary["failures_by_error"] = dict(sorted(Counter(
        attempt.error_code for attempt in attempts if not attempt.ok and attempt.error_code
    ).items()))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a NetBalance benchmark")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output", type=Path, help="Optional summary JSON path")
    args = parser.parse_args(argv)
    metadata_path = args.metadata or args.csv_file.with_name(args.csv_file.name + ".meta.json")
    try:
        attempts = read_attempts_from_csv(args.csv_file)
        if not attempts:
            raise ValueError("CSV contains no attempts")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        recorded = metadata["summary"]
        if recorded["total_attempts"] != len(attempts):
            raise ValueError("CSV row count does not match metadata")
        summary = analyze(attempts, float(recorded["duration_s"]))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
