"""Benchmark tool for NetBalance.

Runs a workload and saves metadata to trace results to config/data/version.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    from .workload import build_parser, run_workload, write_csv
except ImportError as e:
    print(f"Failed to import from workload: {e}", file=sys.stderr)
    sys.exit(1)


def get_git_commit() -> str:
    """Return the short git commit hash of the current repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def get_config_from_service(host: str, port: int) -> dict:
    """Query the NetBalance service for its current configuration."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/config", timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # Add our own argument for metadata output
    parser.add_argument(
        "--metadata-output",
        type=Path,
        help="Output metadata JSON path (default: derived from --output)",
    )
    args = parser.parse_args(argv)

    # Determine the metadata output path
    if args.metadata_output:
        metadata_output = args.metadata_output
    else:
        if not args.output:
            print("Error: --output is required to derive metadata output path", file=sys.stderr)
            return 1
        output_path = Path(args.output)
        metadata_output = output_path.with_name(output_path.name + ".meta.json")

    # Run the workload
    try:
        results, summary = asyncio.run(
            run_workload(
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
            )
        )
    except Exception as e:
        print(f"Error running workload: {e}", file=sys.stderr)
        return 1

    # Write the CSV
    if args.output:
        try:
            write_csv(results, args.output)
        except Exception as e:
            print(f"Error writing CSV: {e}", file=sys.stderr)
            return 1

    # Generate metadata
    # Convert args namespace to a dict, but replace Path objects with strings
    args_dict = {}
    for key, value in vars(args).items():
        if isinstance(value, Path):
            args_dict[key] = str(value)
        else:
            args_dict[key] = value

    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "command_line": " ".join(sys.argv),
        "arguments": args_dict,
    }

    # If we have a host and port, we can try to fetch the config from the service
    if args.host and args.port:
        try:
            config_from_service = get_config_from_service(args.host, args.port)
            metadata["service_config"] = config_from_service
        except Exception as e:
            metadata["service_config_error"] = str(e)

    # Write metadata
    try:
        with metadata_output.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        print(f"Error writing metadata: {e}", file=sys.stderr)
        return 1

    print(f"Benchmark completed. Results saved to {args.output}")
    print(f"Metadata saved to {metadata_output}")

    return 0

if __name__ == "__main__":
    sys.exit(main())