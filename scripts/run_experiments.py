"""Execute the frozen B5 controlled experiment matrix with traceable evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import sys
import time
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from netbalance.benchmark import get_git_commit
from netbalance.config import load_config
from netbalance.demo import DemoLauncher
from netbalance.workload import AttemptResult, run_workload, write_csv


POLICIES = ("rr", "lc", "swrr")


@dataclass(frozen=True)
class Profile:
    scenario: str
    backend_profile: str
    concurrency: int
    weights: dict[str, int]


PROFILES = (
    Profile("s1-uniform-c1", "uniform", 1, {"s1": 1, "s2": 1, "s3": 1}),
    Profile("s1-uniform-c30", "uniform", 30, {"s1": 1, "s2": 1, "s3": 1}),
    Profile("s2-slow-c30", "slow-server", 30, {"s1": 1, "s2": 1, "s3": 1}),
    Profile("s3-capacity-c30", "capacity", 30, {"s1": 5, "s2": 3, "s3": 2}),
)


def policy_order(repetition: int) -> tuple[str, str, str]:
    offset = (repetition - 1) % len(POLICIES)
    return POLICIES[offset:] + POLICIES[:offset]


def make_trace(seed: int, count: int = 300) -> list[dict[str, object]]:
    rng = random.Random(seed)
    return [
        {
            "id": f"req-{index:06d}",
            "op": "work",
            "work_units": rng.randint(1, 3),
            "payload": f"payload-{index:06d}-" + "x" * rng.randint(8, 32),
        }
        for index in range(count)
    ]


def http_json(port: int, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} did not return an object")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_trace(path: Path, requests: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(request) + "\n" for request in requests), encoding="utf-8")


def summarize(results: list[AttemptResult], summary: object, epoch: int) -> dict[str, object]:
    value = asdict(summary)
    value["metrics_epoch"] = epoch
    value["assignments_by_backend"] = dict(sorted(Counter(
        result.backend_id for result in results if result.ok and result.backend_id
    ).items()))
    value["failures_by_error"] = dict(sorted(Counter(
        result.error_code for result in results if not result.ok and result.error_code
    ).items()))
    return value


async def wait_for_healthy(http_port: int) -> None:
    async with asyncio.timeout(15):
        while True:
            health = await asyncio.to_thread(http_json, http_port, "/api/health")
            if health.get("backends") and all(
                backend["health"] == "healthy" for backend in health["backends"]
            ):
                return
            await asyncio.sleep(0.1)


async def run_profile(
    profile: Profile,
    profile_index: int,
    output_root: Path,
    launcher: DemoLauncher,
) -> list[dict[str, object]]:
    config = launcher.config
    launcher.start()
    records: list[dict[str, object]] = []
    try:
        await wait_for_healthy(config.http_port)
        for repetition in range(1, 4):
            seed = 42000 + profile_index * 100 + repetition
            trace = make_trace(seed)
            for policy in policy_order(repetition):
                run_dir = output_root / profile.scenario / policy / str(repetition)
                run_trace = run_dir / "trace.json"
                write_trace(run_trace, trace)
                await asyncio.to_thread(http_json, config.http_port, "/api/algorithm", {"algorithm": policy})
                await asyncio.to_thread(http_json, config.http_port, "/api/weights", {"weights": profile.weights})
                _, warmup = await run_workload(
                    config.listen_host, config.listen_port, count=30,
                    concurrency=profile.concurrency, seed=seed, timeout=config.workload_timeout_s,
                    policy=policy, scenario=profile.scenario, repetition=repetition,
                )
                if warmup.successful_attempts != 30:
                    raise RuntimeError(f"warm-up failed for {profile.scenario}/{policy}/{repetition}")
                reset = await asyncio.to_thread(http_json, config.http_port, "/api/reset", {})
                epoch = int(reset["metrics_epoch"])
                results, measured = await run_workload(
                    config.listen_host, config.listen_port, count=300,
                    concurrency=profile.concurrency, seed=seed, timeout=config.workload_timeout_s,
                    trace_path=run_trace, policy=policy, scenario=profile.scenario,
                    repetition=repetition,
                )
                proxy_metrics = await asyncio.to_thread(http_json, config.http_port, "/api/metrics")
                service_config = await asyncio.to_thread(http_json, config.http_port, "/api/config")
                totals = proxy_metrics["totals"]
                if (
                    proxy_metrics["metrics_epoch"] != epoch
                    or totals["received"] != measured.total_attempts
                    or totals["succeeded"] != measured.successful_attempts
                    or totals["failed"] != measured.failed_attempts
                ):
                    raise RuntimeError(f"client/proxy reconciliation failed for {profile.scenario}/{policy}/{repetition}")
                summary = summarize(results, measured, epoch)
                write_csv(results, run_dir / "raw.csv")
                write_json(run_dir / "summary.json", summary)
                write_json(run_dir / "config.json", service_config)
                write_json(run_dir / "environment.json", {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "git_commit": get_git_commit(),
                    "python": sys.version,
                    "platform": platform.platform(),
                    "inputs": {
                        "scenario": profile.scenario,
                        "backend_profile": profile.backend_profile,
                        "policy": policy,
                        "repetition": repetition,
                        "seed": seed,
                        "warmup_requests": 30,
                        "measured_requests": 300,
                        "concurrency": profile.concurrency,
                        "weights": profile.weights,
                        "policy_order": policy_order(repetition),
                    },
                })
                write_json(run_dir / "proxy-metrics.json", proxy_metrics)
                record = {"scenario": profile.scenario, "policy": policy, "repetition": repetition, **summary}
                records.append(record)
                print(
                    f"{profile.scenario}/{policy}/{repetition}: "
                    f"{measured.successful_attempts}/{measured.total_attempts} succeeded, "
                    f"{measured.throughput_rps:.2f} rps, p95 {measured.p95_latency_ms:.2f} ms",
                    flush=True,
                )
    finally:
        launcher.terminate_all()
    return records


async def run_all(output_root: Path) -> list[dict[str, object]]:
    config = load_config("configs/default.json")
    records: list[dict[str, object]] = []
    for index, profile in enumerate(PROFILES, start=1):
        launcher = DemoLauncher(config, profile.backend_profile, quiet_children=True)
        records.extend(await run_profile(profile, index, output_root, launcher))
        await asyncio.sleep(0.5)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the B5 controlled experiment matrix")
    parser.add_argument("--output", type=Path, default=Path("results/experiments"))
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        records = asyncio.run(run_all(args.output))
        write_json(args.output / "index.json", {
            "schema_version": 1,
            "git_commit": get_git_commit(),
            "run_count": len(records),
            "elapsed_s": time.monotonic() - started,
            "runs": records,
        })
    except Exception as exc:
        print(f"Experiments failed: {exc}", file=sys.stderr)
        return 1
    print(f"Completed {len(records)} measured runs in {time.monotonic() - started:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
