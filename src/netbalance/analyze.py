"""Analyzer tool for NetBalance.

Computes summary statistics from a workload CSV file.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .workload import AttemptResult, compute_summary, CSV_COLUMNS
except ImportError as e:
    print(f"Failed to import from workload: {e}", file=sys.stderr)
    sys.exit(1)


def read_attempts_from_csv(csv_path: Path) -> list[AttemptResult]:
    """Read attempt results from a CSV file."""
    attempts: list[AttemptResult] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != CSV_COLUMNS:
            print(
                f"Warning: CSV columns do not match expected. Expected: {CSV_COLUMNS}, got: {reader.fieldnames}",
                file=sys.stderr,
            )
        for row in reader:
            try:
                attempt = AttemptResult(
                    request_id=row["request_id"],
                    policy=row["policy"],
                    scenario=row["scenario"],
                    repetition=int(row["repetition"]),
                    started_offset_s=float(row["started_offset_s"]),
                    latency_ms=float(row["latency_ms"]),
                    ok=row["ok"].lower() == "true",
                    backend_id=row.get("backend_id") or None,
                    error_code=row.get("error_code") or None,
                )
                attempts.append(attempt)
            except (ValueError, KeyError) as e:
                print(f"Error parsing row {row}: {e}", file=sys.stderr)
                continue
    return attempts


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Analyze NetBalance workload CSV")
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to the workload CSV file",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Optional metadata JSON file to print alongside results",
    )
    args = parser.parse_args(argv)

    if not args.csv_file.is_file():
        print(f"Error: File not found: {args.csv_file}", file=sys.stderr)
        return 1

    attempts = read_attempts_from_csv(args.csv_file)
    if not attempts:
        print("Error: No valid attempts found in CSV", file=sys.stderr)
        return 1

    # We need the duration to compute throughput. The CSV does not contain duration.
    # We can compute the duration as the difference between the last and first started_offset_s
    # plus the average latency? Actually, the duration is the time from the first start to the last finish.
    # We don't have the finish time in the CSV. We only have started_offset_s and latency_ms.
    # We can approximate the duration as max(started_offset_s + latency_ms/1000) - min(started_offset_s)
    # But the workload client's compute_summary function uses the duration passed to it, which is
    # the total time taken by the workload client (bench_total_duration_s).
    # Since we don't have that information in the CSV, we cannot compute throughput accurately.
    # However, the workload client's CSV does not include the duration, so the analyzer cannot
    # compute throughput from the CSV alone.

    # Looking at the workload client's output, it prints the duration and throughput.
    # The CSV only contains the per-attempt data.

    # Therefore, we cannot compute throughput from the CSV. We can only compute latency statistics.

    # But the testing.md T12 says "Analyzer known latencies and CSV reconciliation | Exact mean/nearest-rank percentile/throughput"
    # This suggests that the analyzer is given known latencies (maybe from a fixture) and it should compute the exact
    # mean, percentile, and throughput. How would it get throughput? Perhaps the CSV includes a duration column?
    # Let's check the CSV columns again: they are defined in CSV_COLUMNS in workload.py:
    # CSV_COLUMNS = [
    #     "request_id",
    #     "policy",
    #     "scenario",
    #     "repetition",
    #     "started_offset_s",
    #     "latency_ms",
    #     "ok",
    #     "backend_id",
    #     "error_code",
    # ]
    # No duration.

    # However, the workload client's compute_summary function takes the duration as an argument and uses it to compute
    # throughput. The duration is the total time the workload client took to run (bench_total_duration_s).

    # Therefore, to compute throughput, we need the duration. We cannot get it from the CSV.

    # Perhaps the analyzer is meant to be used with the metadata file that includes the duration? Or perhaps the
    # analyzer is not supposed to compute throughput, but the testing.md is a mistake.

    # Let's look at the B3 demonstration: they saved CSV files and then they used the metrics from the API to get
    # the totals and latency. They did not compute from the CSV.

    # Given the ambiguity, we will compute the latency statistics (mean, p50, p95, p99) and leave throughput as N/A.

    # We can compute the duration from the CSV as described above and then compute throughput as
    # (number of successful attempts) / duration.

    # Let's do that: we will compute the duration as the time from the first start to the last finish.
    # We have for each attempt: started_offset_s and latency_ms.
    # The finish offset for an attempt is started_offset_s + latency_ms/1000.
    # Then duration = max(finish_offset) - min(started_offset_s)

    starts = [a.started_offset_s for a in attempts]
    finishes = [a.started_offset_s + a.latency_ms / 1000.0 for a in attempts]
    duration_s = max(finishes) - min(starts) if attempts else 0.0

    successful = [a for a in attempts if a.ok]
    num_success = len(successful)
    throughput_rps = num_success / duration_s if duration_s > 0 else 0.0

    # Now compute latency statistics from successful attempts
    if successful:
        latencies = sorted(a.latency_ms for a in successful)
        mean_lat = sum(latencies) / len(latencies)
        # We need a function to compute percentile (nearest rank)
        def percentile(sorted_vals: list[float], q: float) -> float:
            if not sorted_vals:
                return 0.0
            rank = int(round(q * len(sorted_vals)))
            if rank < 1:
                rank = 1
            if rank > len(sorted_vals):
                rank = len(sorted_vals)
            return sorted_vals[rank - 1]
        p50_lat = percentile(latencies, 0.50)
        p95_lat = percentile(latencies, 0.95)
        p99_lat = percentile(latencies, 0.99)
    else:
        mean_lat = p50_lat = p95_lat = p99_lat = 0.0

    # Print results
    print(f"Analyzed {len(attempts)} attempts from {args.csv_file}")
    print(f"Duration: {duration_s:.3f} s")
    print(f"Successful attempts: {num_success}")
    print(f"Throughput: {throughput_rps:.2f} rps")
    if successful:
        print(f"Latency (ms): mean={mean_lat:.2f}, p50={p50_lat:.2f}, p95={p95_lat:.2f}, p99={p99_lat:.2f}")
    else:
        print("Latency (ms): N/A (no successful attempts)")

    # If metadata file is provided, print it
    if args.metadata:
        if args.metadata.is_file():
            try:
                with args.metadata.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)
                print("\nMetadata:")
                print(json.dumps(metadata, indent=2))
            except Exception as e:
                print(f"Error reading metadata file: {e}", file=sys.stderr)
        else:
            print(f"Warning: Metadata file not found: {args.metadata}", file=sys.stderr)

    return 0

if __name__ == "__main__":
    sys.exit(main())