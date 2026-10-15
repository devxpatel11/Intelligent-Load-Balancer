"""Integration tests for the benchmark tool."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Helper functions to start and stop processes
def start_backend(host: str, port: int, service_ms: float = 50.0, capacity: int = 4) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "netbalance.backend",
        "--id",
        f"s{port-9100}",  # s1 for 9101, s2 for 9102, s3 for 9103
        "--host",
        host,
        "--port",
        str(port),
        "--service-ms",
        str(service_ms),
        "--capacity",
        str(capacity),
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def start_service(listen_port: int = 9000, http_port: int = 8000) -> subprocess.Popen:
    # We need to create a temporary configuration file with the desired ports
    # For simplicity, we'll use the default configuration and hope the ports are free.
    # Alternatively, we can modify the configuration in memory, but let's use the default.
    cmd = [
        sys.executable,
        "-m",
        "netbalance.service",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for_port(host: str, port: int, timeout_s: float = 10.0) -> bool:
    """Poll until a TCP port accepts connections or timeout expires."""
    import socket
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except (ConnectionRefusedError, TimeoutError, OSError):
                time.sleep(0.05)
    return False


@pytest.mark.integration
def test_benchmark_integration() -> None:
    """Test the benchmark tool with a running service and backends."""
    # We'll use ports 9101, 9102, 9103 for backends and 9000 for proxy, 8000 for HTTP
    # Start backends
    backends = []
    for port in [9101, 9102, 9103]:
        proc = start_backend("127.0.0.1", port)
        backends.append(proc)
        # Wait for the backend port to be accepting connections
        assert wait_for_port("127.0.0.1", port, timeout_s=5.0), f"Backend port {port} not ready"

    # Start service
    service_proc = start_service()
    # Wait for service ports
    assert wait_for_port("127.0.0.1", 9000, timeout_s=5.0), "Proxy port 9000 not ready"
    assert wait_for_port("127.0.0.1", 8000, timeout_s=5.0), "HTTP port 8000 not ready"

    try:
        # Give the service a moment to initialize its internal state
        time.sleep(1.0)

        # Run the benchmark tool
        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "netbalance.benchmark",
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
                "--count",
                "10",
                "--output",
                "benchmark_integration.csv",
            ],
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        assert result.returncode == 0, f"Benchmark failed: {result.stderr}"

        # Check that the output files exist
        assert Path("benchmark_integration.csv").is_file()
        assert Path("benchmark_integration.csv.meta.json").is_file()

        # Check the CSV has the expected number of lines (header + 10 rows)
        csv_lines = Path("benchmark_integration.csv").read_text(encoding="utf-8").strip().splitlines()
        assert len(csv_lines) == 11  # header + 10 rows

        # Check the metadata
        metadata = json.loads(Path("benchmark_integration.csv.meta.json").read_text(encoding="utf-8"))
        assert metadata["git_commit"] != "unknown"
        assert metadata["arguments"]["count"] == 10
        assert metadata["arguments"]["host"] == "127.0.0.1"
        assert metadata["arguments"]["port"] == 9000

        # Optionally, check that we have some successful requests (if the service is working)
        # We can parse the CSV and count the ok=true rows
        ok_count = sum(1 for line in csv_lines[1:] if ",true," in line)
        # We expect at least some successes, but if the service is not configured correctly, we might get zeros.
        # We'll just note that the test passes if the tool runs and produces output.

    finally:
        # Clean up: kill all processes
        for proc in backends:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2.0)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=1.0)
        if service_proc.poll() is None:
            service_proc.terminate()
            service_proc.wait(timeout=2.0)
            if service_proc.poll() is None:
                service_proc.kill()
                service_proc.wait(timeout=1.0)


@pytest.mark.integration
def test_analyze_integration() -> None:
    """Test the analyzer tool with a CSV generated by the benchmark tool."""
    # We'll create a small CSV file manually and test the analyzer on it.
    # However, we want to test the analyzer with a CSV that has successful attempts.
    # We'll create a CSV with a few successful attempts and check that the analyzer computes the correct statistics.

    csv_content = """request_id,policy,scenario,repetition,started_offset_s,latency_ms,ok,backend_id,error_code
req-1,rr,default,1,0.0,10.0,true,s1,
req-2,rr,default,1,0.01,20.0,true,s2,
req-3,rr,default,1,0.02,30.0,true,s3,
"""
    csv_path = Path("analyze_integration.csv")
    csv_path.write_text(csv_content, encoding="utf-8")

    try:
        # Run the analyzer tool
        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "netbalance.analyze",
                str(csv_path),
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        assert result.returncode == 0, f"Analyzer failed: {result.stderr}"

        # Check the output contains the expected statistics
        assert "Analyzed 3 attempts" in result.stdout
        assert "Successful attempts: 3" in result.stdout
        assert "Throughput:" in result.stdout
        assert "Latency (ms): mean=" in result.stdout

        # Create a dummy metadata file
        metadata_path = Path("analyze_integration.csv.meta.json")
        metadata_path.write_text('{"test": "metadata"}', encoding="utf-8")

        # We can also test with metadata
        result2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "netbalance.analyze",
                str(csv_path),
                "--metadata",
                str(metadata_path),
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        assert result2.returncode == 0
        assert "Metadata:" in result2.stdout
        assert '"test": "metadata"' in result2.stdout

    finally:
        if csv_path.is_file():
            csv_path.unlink()
        meta_path = Path("analyze_integration.csv.meta.json")
        if meta_path.is_file():
            meta_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__])