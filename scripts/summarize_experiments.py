"""Aggregate B5 experiment repetitions and render the comparison chart."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def aggregate(records: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        groups[(str(record["scenario"]), str(record["policy"]))].append(record)
    rows = []
    for (scenario, policy), runs in sorted(groups.items()):
        assignments: Counter[str] = Counter()
        failures: Counter[str] = Counter()
        for run in runs:
            assignments.update(run["assignments_by_backend"])
            failures.update(run["failures_by_error"])
        rows.append({
            "scenario": scenario,
            "policy": policy,
            "repetitions": len(runs),
            "total_attempts": sum(int(run["total_attempts"]) for run in runs),
            "successful_attempts": sum(int(run["successful_attempts"]) for run in runs),
            "failed_attempts": sum(int(run["failed_attempts"]) for run in runs),
            "median_throughput_rps": statistics.median(float(run["throughput_rps"]) for run in runs),
            "median_p95_latency_ms": statistics.median(float(run["p95_latency_ms"]) for run in runs),
            "assignments_by_backend": dict(sorted(assignments.items())),
            "failures_by_error": dict(sorted(failures.items())),
        })
    return rows


def write_outputs(root: Path, rows: list[dict[str, object]]) -> None:
    (root / "aggregate.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with (root / "aggregate.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=[
            "scenario", "policy", "repetitions", "total_attempts", "successful_attempts",
            "failed_attempts", "median_throughput_rps", "median_p95_latency_ms",
            "assignments_by_backend", "failures_by_error",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "assignments_by_backend": json.dumps(row["assignments_by_backend"], sort_keys=True),
                "failures_by_error": json.dumps(row["failures_by_error"], sort_keys=True),
            })


def render_chart(root: Path, rows: list[dict[str, object]]) -> None:
    import matplotlib.pyplot as plt

    scenarios = sorted({str(row["scenario"]) for row in rows})
    policies = ("rr", "lc", "swrr")
    positions = list(range(len(scenarios)))
    width = 0.25
    figure, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    for index, policy in enumerate(policies):
        selected = {(str(row["scenario"]), str(row["policy"])): row for row in rows}
        offset = (index - 1) * width
        axes[0].bar(
            [position + offset for position in positions],
            [selected[(scenario, policy)]["median_throughput_rps"] for scenario in scenarios],
            width, label=policy.upper(),
        )
        axes[1].bar(
            [position + offset for position in positions],
            [selected[(scenario, policy)]["median_p95_latency_ms"] for scenario in scenarios],
            width, label=policy.upper(),
        )
    axes[0].set_ylabel("Successful throughput (requests/s)")
    axes[1].set_ylabel("Successful p95 latency (ms)")
    axes[1].set_xticks(positions, scenarios, rotation=15, ha="right")
    axes[0].set_xticks(positions, scenarios, rotation=15, ha="right")
    axes[0].legend()
    axes[0].set_title("NetBalance B5 controlled experiments (median of 3 repetitions)")
    figure.savefig(root / "comparison.png", dpi=150)
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate B5 experiment evidence")
    parser.add_argument("root", type=Path, nargs="?", default=Path("results/experiments"))
    args = parser.parse_args(argv)
    index = json.loads((args.root / "index.json").read_text(encoding="utf-8"))
    rows = aggregate(index["runs"])
    write_outputs(args.root, rows)
    render_chart(args.root, rows)
    print(f"Wrote {len(rows)} aggregate rows and comparison.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
