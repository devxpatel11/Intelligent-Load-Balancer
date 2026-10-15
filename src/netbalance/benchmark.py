"""Run a workload and save traceable raw data and metadata."""

from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import sys
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .workload import _valid_port, build_parser, run_workload, write_csv


def get_git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def get_config_from_service(host: str, port: int) -> dict[str, object]:
    with urllib.request.urlopen(f"http://{host}:{port}/api/config", timeout=2) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("service configuration response must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.description = "Run a traceable NetBalance benchmark"
    parser.add_argument("--http-host", default="127.0.0.1", help="HTTP API host")
    parser.add_argument("--http-port", type=_valid_port, default=8000, help="HTTP API port")
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args(argv)
    if not args.output:
        parser.error("--output is required")

    output_path = Path(args.output)
    metadata_path = args.metadata_output or output_path.with_name(output_path.name + ".meta.json")
    try:
        service_config = get_config_from_service(args.http_host, args.http_port)
        results, summary = asyncio.run(run_workload(
            host=args.host,
            port=args.port,
            count=args.count,
            duration=args.duration,
            concurrency=args.concurrency,
            seed=args.seed,
            timeout=args.timeout,
            trace_path=args.trace,
            policy=args.policy,
            scenario=args.scenario,
            repetition=args.repetition,
        ))
        write_csv(results, output_path)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": get_git_commit(),
            "environment": {"python": sys.version, "platform": platform.platform()},
            "arguments": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            "service_config": service_config,
            "summary": asdict(summary),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1

    print(f"Benchmark completed: {summary.successful_attempts}/{summary.total_attempts} succeeded")
    print(f"Raw data: {output_path}")
    print(f"Metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
