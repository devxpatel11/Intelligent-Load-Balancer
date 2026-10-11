"""Workload client CLI and execution engine for NetBalance."""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import (
    MAX_FRAME_BYTES,
    ProtocolError,
    encode_message,
    read_message,
    validate_work,
)

CSV_COLUMNS = [
    "request_id",
    "policy",
    "scenario",
    "repetition",
    "started_offset_s",
    "latency_ms",
    "ok",
    "backend_id",
    "error_code",
]


@dataclass(frozen=True, slots=True)
class AttemptResult:
    request_id: str
    policy: str
    scenario: str
    repetition: int
    started_offset_s: float
    latency_ms: float
    ok: bool
    backend_id: str | None
    error_code: str | None

    def to_row(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "policy": self.policy,
            "scenario": self.scenario,
            "repetition": self.repetition,
            "started_offset_s": f"{self.started_offset_s:.6f}",
            "latency_ms": f"{self.latency_ms:.3f}",
            "ok": "true" if self.ok else "false",
            "backend_id": self.backend_id if self.backend_id is not None else "",
            "error_code": self.error_code if self.error_code is not None else "",
        }


@dataclass(frozen=True, slots=True)
class WorkloadSummary:
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    duration_s: float
    throughput_rps: float
    mean_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None


def calculate_percentile(sorted_values: list[float], q: float) -> float | None:
    """Nearest-rank percentile calculation matching metrics contract: sorted[ceil(q * N) - 1]."""
    if not sorted_values:
        return None
    rank = math.ceil(q * len(sorted_values)) - 1
    rank = max(0, min(rank, len(sorted_values) - 1))
    return sorted_values[rank]


def compute_summary(results: list[AttemptResult], duration_s: float) -> WorkloadSummary:
    total = len(results)
    successes = [r for r in results if r.ok]
    num_success = len(successes)
    num_failed = total - num_success

    # Throughput: successful requests / duration_s
    throughput = (num_success / duration_s) if duration_s > 0 else 0.0

    if not successes:
        return WorkloadSummary(
            total_attempts=total,
            successful_attempts=0,
            failed_attempts=num_failed,
            duration_s=duration_s,
            throughput_rps=throughput,
            mean_latency_ms=None,
            p50_latency_ms=None,
            p95_latency_ms=None,
            p99_latency_ms=None,
        )

    latencies = sorted(r.latency_ms for r in successes)
    mean_lat = sum(latencies) / len(latencies)
    p50_lat = calculate_percentile(latencies, 0.50)
    p95_lat = calculate_percentile(latencies, 0.95)
    p99_lat = calculate_percentile(latencies, 0.99)

    return WorkloadSummary(
        total_attempts=total,
        successful_attempts=num_success,
        failed_attempts=num_failed,
        duration_s=duration_s,
        throughput_rps=throughput,
        mean_latency_ms=mean_lat,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        p99_latency_ms=p99_lat,
    )


def write_csv(results: list[AttemptResult], target: io.TextIOBase | Path | str) -> None:
    should_close = False
    if isinstance(target, (str, Path)):
        path = Path(target)
        if path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        file_obj = open(path, "w", newline="", encoding="utf-8")
        should_close = True
    else:
        file_obj = target

    try:
        writer = csv.DictWriter(file_obj, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_row())
    finally:
        if should_close:
            file_obj.close()


async def execute_single_attempt(
    host: str,
    port: int,
    request: dict[str, Any],
    timeout_s: float,
    *,
    policy: str,
    scenario: str,
    repetition: int,
    started_offset_s: float,
) -> AttemptResult:
    req_id = request["id"]
    expected_payload = request.get("payload")
    req_bytes = encode_message(request)

    writer: asyncio.StreamWriter | None = None
    start_time = time.perf_counter()
    backend_id: str | None = None
    error_code: str | None = None
    ok = False

    try:
        async with asyncio.timeout(timeout_s):
            try:
                reader, writer = await asyncio.open_connection(
                    host, port, limit=MAX_FRAME_BYTES
                )
            except (ConnectionRefusedError, ConnectionResetError, OSError):
                return AttemptResult(
                    request_id=req_id,
                    policy=policy,
                    scenario=scenario,
                    repetition=repetition,
                    started_offset_s=started_offset_s,
                    latency_ms=(time.perf_counter() - start_time) * 1_000,
                    ok=False,
                    backend_id=None,
                    error_code="CONNECTION_ERROR",
                )

            writer.write(req_bytes)
            await writer.drain()

            response = await read_message(
                reader,
                timeout_s,
                timeout_code="CLIENT_READ_TIMEOUT",
                invalid_code="INVALID_RESPONSE",
            )

        latency_ms = (time.perf_counter() - start_time) * 1_000

        # Validate response
        resp_id = response.get("id")
        resp_ok = response.get("ok")
        raw_backend_id = response.get("backend_id")
        backend_id = raw_backend_id if isinstance(raw_backend_id, str) and raw_backend_id else None

        if resp_id != req_id:
            ok = False
            error_code = "REQUEST_ID_MISMATCH"
        elif resp_ok is True:
            if not isinstance(backend_id, str) or not backend_id:
                ok = False
                error_code = "MALFORMED_RESPONSE"
            elif expected_payload is not None and response.get("echo") != expected_payload:
                ok = False
                error_code = "MALFORMED_RESPONSE"
            else:
                ok = True
                error_code = None
        elif resp_ok is False and (raw_backend_id is None or backend_id is not None):
            ok = False
            err = response.get("error")
            if (
                isinstance(err, dict)
                and isinstance(err.get("code"), str)
                and err.get("code")
                and isinstance(err.get("message"), str)
                and err.get("message")
            ):
                error_code = str(err["code"])
            else:
                error_code = "MALFORMED_RESPONSE"
        else:
            ok = False
            error_code = "MALFORMED_RESPONSE"

        return AttemptResult(
            request_id=req_id,
            policy=policy,
            scenario=scenario,
            repetition=repetition,
            started_offset_s=started_offset_s,
            latency_ms=latency_ms,
            ok=ok,
            backend_id=backend_id,
            error_code=error_code,
        )

    except TimeoutError:
        latency_ms = (time.perf_counter() - start_time) * 1_000
        return AttemptResult(
            request_id=req_id,
            policy=policy,
            scenario=scenario,
            repetition=repetition,
            started_offset_s=started_offset_s,
            latency_ms=latency_ms,
            ok=False,
            backend_id=None,
            error_code="TIMEOUT",
        )
    except ProtocolError as exc:
        latency_ms = (time.perf_counter() - start_time) * 1_000
        code = "TIMEOUT" if "TIMEOUT" in exc.code else "MALFORMED_RESPONSE"
        return AttemptResult(
            request_id=req_id,
            policy=policy,
            scenario=scenario,
            repetition=repetition,
            started_offset_s=started_offset_s,
            latency_ms=latency_ms,
            ok=False,
            backend_id=None,
            error_code=code,
        )
    except (ConnectionError, OSError):
        latency_ms = (time.perf_counter() - start_time) * 1_000
        return AttemptResult(
            request_id=req_id,
            policy=policy,
            scenario=scenario,
            repetition=repetition,
            started_offset_s=started_offset_s,
            latency_ms=latency_ms,
            ok=False,
            backend_id=None,
            error_code="CONNECTION_ERROR",
        )
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout_s)
            except (TimeoutError, ConnectionError, OSError):
                pass


async def run_workload(
    host: str,
    port: int,
    *,
    count: int | None = None,
    duration: float | None = None,
    concurrency: int = 1,
    seed: int = 42,
    timeout: float = 4.0,
    trace_path: str | Path | None = None,
    policy: str = "rr",
    scenario: str = "default",
    repetition: int = 1,
) -> tuple[list[AttemptResult], WorkloadSummary]:
    if not isinstance(host, str) or not host:
        raise ValueError("host must be a non-empty string")
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"port must be an integer between 1 and 65535, got {port}")
    if count is None and duration is None:
        raise ValueError("Either count or duration must be specified")
    if count is not None and duration is not None:
        raise ValueError("Cannot specify both count and duration")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count <= 0):
        raise ValueError(f"count must be a positive integer, got {count}")
    if duration is not None and (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError(f"duration must be a positive number, got {duration}")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError(f"concurrency must be a positive integer, got {concurrency}")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError(f"timeout must be a positive number, got {timeout}")

    rng = random.Random(seed)

    # Pre-generate or load trace requests if count is specified or trace is provided
    trace_requests: list[dict[str, Any]] | None = None
    if trace_path is not None:
        trace_requests = []
        with open(trace_path, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        request = json.loads(line)
                        if not isinstance(request, dict):
                            raise ValueError("request must be a JSON object")
                        trace_requests.append(validate_work(request))
                    except (json.JSONDecodeError, ProtocolError, ValueError) as exc:
                        raise ValueError(f"invalid trace request at line {line_number}: {exc}") from exc

    bench_start_mono = time.monotonic()
    results: list[AttemptResult] = []
    results_lock = asyncio.Lock()

    if count is not None:
        queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
        for i in range(count):
            if trace_requests and i < len(trace_requests):
                req = dict(trace_requests[i])
            else:
                work_units = rng.randint(1, 3)
                payload_len = rng.randint(8, 32)
                payload_str = f"payload-{i:06d}-" + ("x" * payload_len)
                req = {
                    "id": f"req-{i:06d}",
                    "op": "work",
                    "work_units": work_units,
                    "payload": payload_str,
                }
            queue.put_nowait((i, req))

        async def worker() -> None:
            while True:
                try:
                    _, req = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                offset_s = time.monotonic() - bench_start_mono
                res = await execute_single_attempt(
                    host=host,
                    port=port,
                    request=req,
                    timeout_s=timeout,
                    policy=policy,
                    scenario=scenario,
                    repetition=repetition,
                    started_offset_s=offset_s,
                )
                async with results_lock:
                    results.append(res)
                queue.task_done()

        num_workers = min(concurrency, count)
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
        await asyncio.gather(*workers)

    else:
        assert duration is not None
        stop_mono = bench_start_mono + duration
        next_req_id = 0
        req_id_lock = asyncio.Lock()

        async def duration_worker() -> None:
            nonlocal next_req_id
            while True:
                if time.monotonic() >= stop_mono:
                    break
                async with req_id_lock:
                    idx = next_req_id
                    next_req_id += 1
                    if trace_requests and idx < len(trace_requests):
                        req = dict(trace_requests[idx])
                    else:
                        work_units = rng.randint(1, 3)
                        payload_str = f"payload-{idx:06d}"
                        req = {
                            "id": f"req-{idx:06d}",
                            "op": "work",
                            "work_units": work_units,
                            "payload": payload_str,
                        }

                offset_s = time.monotonic() - bench_start_mono
                res = await execute_single_attempt(
                    host=host,
                    port=port,
                    request=req,
                    timeout_s=timeout,
                    policy=policy,
                    scenario=scenario,
                    repetition=repetition,
                    started_offset_s=offset_s,
                )
                async with results_lock:
                    results.append(res)

        workers = [asyncio.create_task(duration_worker()) for _ in range(concurrency)]
        await asyncio.gather(*workers)

    bench_total_duration_s = time.monotonic() - bench_start_mono
    results.sort(key=lambda r: r.started_offset_s)
    summary = compute_summary(results, bench_total_duration_s)
    return results, summary


def _positive_int(val: str) -> int:
    try:
        ival = int(val)
        if ival <= 0:
            raise ValueError
        return ival
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got '{val}'")


def _positive_float(val: str) -> float:
    try:
        fval = float(val)
        if fval <= 0 or math.isnan(fval) or math.isinf(fval):
            raise ValueError
        return fval
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a positive number, got '{val}'")


def _valid_port(val: str) -> int:
    try:
        ival = int(val)
        if not (1 <= ival <= 65535):
            raise ValueError
        return ival
    except ValueError:
        raise argparse.ArgumentTypeError(f"port must be an integer between 1 and 65535, got '{val}'")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NetBalance Workload Client")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Target proxy host")
    parser.add_argument("--port", type=_valid_port, default=9000, help="Target proxy port (1-65535)")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--count", type=_positive_int, help="Number of work requests to send (> 0)")
    mode_group.add_argument("--duration", type=_positive_float, help="Duration in seconds to run workload (> 0)")

    parser.add_argument("--concurrency", type=_positive_int, default=1, help="Max bounded concurrency (> 0)")
    parser.add_argument("--seed", type=int, default=42, help="Seed for RNG reproducibility")
    parser.add_argument("--timeout", type=_positive_float, default=4.0, help="Per-attempt timeout in seconds (> 0)")
    parser.add_argument("--output", type=str, help="Output CSV path")
    parser.add_argument("--trace", type=str, help="Optional trace file path with pre-generated requests")

    # Run metadata
    parser.add_argument("--policy", type=str, default="rr", help="Load balancing policy label")
    parser.add_argument("--scenario", type=str, default="default", help="Benchmark scenario label")
    parser.add_argument("--repetition", type=int, default=1, help="Repetition index")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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

    if args.output:
        write_csv(results, args.output)

    print(
        f"Workload completed: {summary.total_attempts} attempts "
        f"({summary.successful_attempts} succeeded, {summary.failed_attempts} failed) "
        f"in {summary.duration_s:.3f}s"
    )
    print(f"Throughput: {summary.throughput_rps:.2f} rps")
    if summary.mean_latency_ms is not None:
        print(
            f"Latency (ms): mean={summary.mean_latency_ms:.2f}, "
            f"p50={summary.p50_latency_ms:.2f}, "
            f"p95={summary.p95_latency_ms:.2f}, "
            f"p99={summary.p99_latency_ms:.2f}"
        )
    else:
        print("Latency (ms): N/A (no successful attempts)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
