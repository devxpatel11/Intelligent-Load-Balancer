"""Run the bounded G6 live-demo rehearsal without changing saved evidence."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from collections import Counter

from netbalance.config import load_config
from netbalance.demo import DemoLauncher, is_port_in_use
from netbalance.workload import run_workload
from run_experiments import http_json, wait_for_healthy


async def rehearse() -> dict[str, object]:
    config = load_config("configs/default.json")
    launcher = DemoLauncher(config, "uniform", quiet_children=True)
    ports = [
        (config.listen_host, config.listen_port),
        (config.http_host, config.http_port),
        *((backend.host, backend.port) for backend in config.backends),
    ]
    launcher.start()
    try:
        await wait_for_healthy(config.http_port)
        with urllib.request.urlopen(f"http://{config.http_host}:{config.http_port}/", timeout=3) as response:
            dashboard_ok = response.status == 200 and b"NetBalance" in response.read()
        if not dashboard_ok:
            raise RuntimeError("dashboard rehearsal failed")
        await asyncio.to_thread(http_json, config.http_port, "/api/algorithm", {"algorithm": "rr"})
        await asyncio.to_thread(http_json, config.http_port, "/api/reset", {})
        results, summary = await run_workload(
            config.listen_host,
            config.listen_port,
            count=30,
            concurrency=6,
            seed=606,
            timeout=config.workload_timeout_s,
            policy="rr",
            scenario="g6-rehearsal",
        )
        assignments = dict(sorted(Counter(result.backend_id for result in results if result.ok).items()))
        metrics = await asyncio.to_thread(http_json, config.http_port, "/api/metrics")
        if summary.successful_attempts != 30 or summary.failed_attempts != 0:
            raise RuntimeError("rehearsal workload did not complete 30/30")
        if assignments != {"s1": 10, "s2": 10, "s3": 10}:
            raise RuntimeError(f"unexpected RR distribution: {assignments}")
        if metrics["inflight"] != 0 or metrics["totals"]["received"] != 30:
            raise RuntimeError("proxy accounting did not settle after rehearsal")
        result = {"successful": 30, "failed": 0, "assignments": assignments, "dashboard_status": 200}
    finally:
        launcher.terminate_all()

    deadline = time.monotonic() + 5
    while any(is_port_in_use(host, port) for host, port in ports) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    occupied = [f"{host}:{port}" for host, port in ports if is_port_in_use(host, port)]
    if occupied:
        raise RuntimeError(f"owned ports were not released: {', '.join(occupied)}")
    result["ports_released"] = True
    return result


def main() -> int:
    print(json.dumps(asyncio.run(rehearse()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
