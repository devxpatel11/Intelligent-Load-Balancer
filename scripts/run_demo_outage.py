"""Script to execute the complete B3 live demonstration and record results."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# Subprocesses
p_s1 = subprocess.Popen([sys.executable, "-m", "netbalance.backend", "--id", "s1", "--port", "9101", "--service-ms", "50", "--capacity", "4"])
p_s2 = subprocess.Popen([sys.executable, "-m", "netbalance.backend", "--id", "s2", "--port", "9102", "--service-ms", "50", "--capacity", "4"])
p_s3 = subprocess.Popen([sys.executable, "-m", "netbalance.backend", "--id", "s3", "--port", "9103", "--service-ms", "50", "--capacity", "4"])
p_svc = subprocess.Popen([sys.executable, "-m", "netbalance.service"])


def cleanup() -> None:
    for p in (p_svc, p_s1, p_s2, p_s3):
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=2) as resp:
        return json.loads(resp.read().decode())


def http_post(path: str, data: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return json.loads(resp.read().decode())


try:
    print("Waiting for backends to become healthy...")
    time.sleep(2.5)
    for _ in range(20):
        try:
            h = http_get("/api/health")
            states = [b["health"] for b in h.get("backends", [])]
            if states == ["healthy", "healthy", "healthy"]:
                print(f"All backends healthy: {states}")
                break
        except Exception:
            pass
        time.sleep(0.5)

    # Step 1: 30 requests using round-robin
    print("\n--- Step 1: 30 requests using Round-Robin ---")
    res = subprocess.run([
        sys.executable, "-m", "netbalance.workload",
        "--count", "30", "--concurrency", "6",
        "--output", str(RESULTS_DIR / "demo_rr_30.csv"),
        "--policy", "rr", "--scenario", "demo"
    ], capture_output=True, text=True)
    print("RR workload exit code:", res.returncode)
    m_rr = http_get("/api/metrics")
    print(f"RR metrics: succeeded={m_rr['totals']['succeeded']}, assignments={[b['assignments'] for b in m_rr['backends']]}")

    # Step 2: Switch policy to swrr and weights to 5:3:2
    print("\n--- Step 2: Switch policy to swrr and weights 5:3:2 ---")
    http_post("/api/algorithm", {"algorithm": "swrr"})
    http_post("/api/weights", {"weights": {"s1": 5, "s2": 3, "s3": 2}})
    # Reset metrics
    http_post("/api/reset", {})
    print("Reset metrics after configuring SWRR 5:3:2.")

    # Step 3: Run 30 requests to show weights & active counts
    print("Running 30 requests under SWRR 5:3:2...")
    res = subprocess.run([
        sys.executable, "-m", "netbalance.workload",
        "--count", "30", "--concurrency", "6",
        "--output", str(RESULTS_DIR / "demo_swrr_30.csv"),
        "--policy", "swrr", "--scenario", "demo"
    ], capture_output=True, text=True)
    m_swrr = http_get("/api/metrics")
    print(f"SWRR metrics: succeeded={m_swrr['totals']['succeeded']}, assignments={[b['assignments'] for b in m_swrr['backends']]}")

    # Reset metrics for Step 4 & 5
    http_post("/api/reset", {})

    # Step 4 & 5: 15-second workload, stop s2 at 3s, restart at 8s
    print("\n--- Step 4 & 5: 15-second workload with s2 stop at 3s and restart at 8s ---")
    t_start = time.time()
    p_wl = subprocess.Popen([
        sys.executable, "-m", "netbalance.workload",
        "--duration", "15", "--concurrency", "6",
        "--output", str(RESULTS_DIR / "demo_outage_recovery.csv"),
        "--policy", "swrr", "--scenario", "outage_recovery"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    time.sleep(3.0)
    t_stop_s2 = time.time()
    print(f"[{t_stop_s2 - t_start:.2f}s] Stopping s2 backend process...")
    p_s2.terminate()
    p_s2.wait()

    time.sleep(5.0)
    t_restart_s2 = time.time()
    print(f"[{t_restart_s2 - t_start:.2f}s] Restarting s2 backend process...")
    p_s2 = subprocess.Popen([sys.executable, "-m", "netbalance.backend", "--id", "s2", "--port", "9102", "--service-ms", "50", "--capacity", "4"])

    stdout, stderr = p_wl.communicate()
    t_end = time.time()
    print(f"[{t_end - t_start:.2f}s] Workload finished!")
    print(stdout)

    # Wait for s2 to recover to healthy
    print("Waiting for s2 recovery in proxy health registry...")
    for _ in range(10):
        m = http_get("/api/metrics")
        s2_rec = next(b for b in m["backends"] if b["id"] == "s2")
        if s2_rec["health"] == "healthy":
            print(f"s2 recovered! Current health: {s2_rec['health']}")
            break
        time.sleep(0.5)

    m_final = http_get("/api/metrics")
    demo_meta = {
        "timestamps": {
            "t_start": t_start,
            "t_stop_s2": t_stop_s2,
            "t_restart_s2": t_restart_s2,
            "t_end": t_end,
            "stop_offset_s": t_stop_s2 - t_start,
            "restart_offset_s": t_restart_s2 - t_start,
            "total_duration_s": t_end - t_start,
        },
        "step1_rr": m_rr,
        "step2_swrr": m_swrr,
        "step4_5_outage_metrics": m_final,
    }
    with open(RESULTS_DIR / "demo_outage_meta.json", "w", encoding="utf-8") as f:
        json.dump(demo_meta, f, indent=2)

    print("\nDemonstration completed successfully. Results saved to results/ directory.")
finally:
    cleanup()
