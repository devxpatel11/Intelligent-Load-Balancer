import csv
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from netbalance.demo import is_port_in_use


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_healthy(http_port: int, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/api/health", timeout=0.2) as response:
                health = json.loads(response.read())
            if all(backend["health"] == "healthy" for backend in health["backends"]):
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError("service and backends did not become healthy")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def test_benchmark_and_analyzer_over_real_loopback(tmp_path: Path) -> None:
    proxy_port, http_port = free_port(), free_port()
    backend_ports = [free_port() for _ in range(3)]
    config = {
        "listen_host": "127.0.0.1", "listen_port": proxy_port,
        "http_host": "127.0.0.1", "http_port": http_port,
        "algorithm": "rr", "max_inflight": 20,
        "client_frame_timeout_s": 0.5, "backend_connect_timeout_s": 0.2,
        "backend_timeout_s": 1.0, "workload_timeout_s": 2.0,
        "health_interval_s": 0.05, "health_timeout_s": 0.1,
        "fail_threshold": 2, "recover_threshold": 2,
        "backends": [
            {"id": f"s{index}", "host": "127.0.0.1", "port": port, "weight": 1}
            for index, port in enumerate(backend_ports, 1)
        ],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "netbalance.backend", "--id", f"s{index}", "--port", str(port), "--service-ms", "2"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for index, port in enumerate(backend_ports, 1)
    ]
    processes.append(subprocess.Popen(
        [sys.executable, "-m", "netbalance.service", "--config", str(config_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ))
    raw_path = tmp_path / "dry-run.csv"
    summary_path = tmp_path / "summary.json"
    try:
        wait_until_healthy(http_port)
        benchmark = subprocess.run([
            sys.executable, "-m", "netbalance.benchmark",
            "--host", "127.0.0.1", "--port", str(proxy_port),
            "--http-host", "127.0.0.1", "--http-port", str(http_port),
            "--count", "30", "--concurrency", "6", "--output", str(raw_path),
        ], capture_output=True, text=True, timeout=15)
        assert benchmark.returncode == 0, benchmark.stderr
        rows = list(csv.DictReader(raw_path.open(newline="", encoding="utf-8")))
        assert len(rows) == 30
        assert all(row["ok"] == "true" for row in rows)
        metadata = json.loads((tmp_path / "dry-run.csv.meta.json").read_text(encoding="utf-8"))
        assert metadata["service_config"]["listen_port"] == proxy_port
        assert metadata["summary"]["successful_attempts"] == 30

        analyzer = subprocess.run([
            sys.executable, "-m", "netbalance.analyze", str(raw_path), "--output", str(summary_path)
        ], capture_output=True, text=True, timeout=5)
        assert analyzer.returncode == 0, analyzer.stderr
        assert json.loads(summary_path.read_text(encoding="utf-8"))["total_attempts"] == 30
    finally:
        for process in reversed(processes):
            stop(process)

    for port in [proxy_port, http_port, *backend_ports]:
        assert not is_port_in_use("127.0.0.1", port)
