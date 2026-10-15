"""Portable launcher and orchestrator for NetBalance live demo.

Starts the three backend subprocesses and the proxy/service subprocess using
sys.executable and the provided configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .config import AppConfig, load_config

logger = logging.getLogger("netbalance.demo")

# Scenario / profile presets
# S1: uniform (all 50ms, capacity 4)
# S2: slow-server (s1/s3 50ms, s2 200ms; capacity 4)
# S3: capacity / unequal-capacity (all 50ms; capacities s1=5, s2=3, s3=2)
PROFILE_PRESETS: dict[str, dict[str, dict[str, float | int]]] = {
    "uniform": {
        "s1": {"service_ms": 50.0, "capacity": 4},
        "s2": {"service_ms": 50.0, "capacity": 4},
        "s3": {"service_ms": 50.0, "capacity": 4},
    },
    "slow-server": {
        "s1": {"service_ms": 50.0, "capacity": 4},
        "s2": {"service_ms": 200.0, "capacity": 4},
        "s3": {"service_ms": 50.0, "capacity": 4},
    },
    "capacity": {
        "s1": {"service_ms": 50.0, "capacity": 5},
        "s2": {"service_ms": 50.0, "capacity": 3},
        "s3": {"service_ms": 50.0, "capacity": 2},
    },
}


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a TCP port is currently occupied by an active listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False


def wait_for_port(host: str, port: int, timeout_s: float = 5.0) -> bool:
    """Poll until a TCP port accepts connections or timeout expires."""
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


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]


class DemoLauncher:
    """Orchestrates starting, readiness-checking, and cleaning up demo processes."""

    def __init__(
        self,
        config: AppConfig,
        profile: str = "uniform",
        custom_backend_overrides: Mapping[str, Mapping[str, float | int]] | None = None,
    ) -> None:
        self.config = config
        self.profile = profile
        self.backend_overrides = custom_backend_overrides or PROFILE_PRESETS.get(profile, {})
        self.processes: list[ManagedProcess] = []

    def verify_ports_available(self) -> None:
        """Verify none of the required ports are occupied by pre-existing processes."""
        ports_to_check = [
            (self.config.listen_host, self.config.listen_port, f"Proxy port {self.config.listen_port}"),
            (self.config.http_host, self.config.http_port, f"HTTP/Dashboard port {self.config.http_port}"),
        ]
        for b in self.config.backends:
            ports_to_check.append((b.host, b.port, f"Backend {b.id} port {b.port}"))

        occupied = []
        for host, port, desc in ports_to_check:
            if is_port_in_use(host, port):
                occupied.append(f"{desc} ({host}:{port})")

        if occupied:
            msg = (
                f"Cannot launch demo: required port(s) already in use: {', '.join(occupied)}. "
                "Ensure no existing instances are running. The launcher will never kill unknown processes."
            )
            logger.error(msg)
            raise RuntimeError(msg)

    def start(self, startup_timeout_s: float = 10.0) -> None:
        """Start backend and service subprocesses and verify readiness."""
        self.verify_ports_available()

        # 1. Start backends
        for b in self.config.backends:
            overrides = self.backend_overrides.get(b.id, {})
            service_ms = overrides.get("service_ms", 50.0)
            capacity = overrides.get("capacity", 4)

            cmd = [
                sys.executable,
                "-m",
                "netbalance.backend",
                "--id",
                str(b.id),
                "--host",
                str(b.host),
                "--port",
                str(b.port),
                "--service-ms",
                str(service_ms),
                "--capacity",
                str(capacity),
            ]
            logger.info("Starting backend %s on %s:%d (service=%sms, cap=%d)...", b.id, b.host, b.port, service_ms, capacity)
            proc = subprocess.Popen(
                cmd,
                text=True,
            )
            self.processes.append(ManagedProcess(name=f"backend-{b.id}", process=proc))

        # 2. Wait for backends to accept connections
        for b in self.config.backends:
            if not wait_for_port(b.host, b.port, timeout_s=startup_timeout_s):
                self._check_child_failures()
                self.terminate_all()
                raise RuntimeError(f"Backend {b.id} ({b.host}:{b.port}) failed to become ready within {startup_timeout_s}s.")

        # 3. Start proxy/service
        service_cmd = [
            sys.executable,
            "-m",
            "netbalance.service",
            "--http-port",
            str(self.config.http_port),
        ]
        logger.info("Starting NetBalance service (proxy :%d, HTTP :%d)...", self.config.listen_port, self.config.http_port)
        service_proc = subprocess.Popen(
            service_cmd,
            text=True,
        )
        self.processes.append(ManagedProcess(name="service", process=service_proc))

        # 4. Wait for proxy and HTTP service ports
        if not wait_for_port(self.config.listen_host, self.config.listen_port, timeout_s=startup_timeout_s):
            self._check_child_failures()
            self.terminate_all()
            raise RuntimeError(f"Proxy port {self.config.listen_port} failed to become ready within {startup_timeout_s}s.")

        if not wait_for_port(self.config.http_host, self.config.http_port, timeout_s=startup_timeout_s):
            self._check_child_failures()
            self.terminate_all()
            raise RuntimeError(f"HTTP port {self.config.http_port} failed to become ready within {startup_timeout_s}s.")

        logger.info("All demo processes started and ready.")

    def _check_child_failures(self) -> None:
        """Check if any child process has terminated prematurely and log its stderr."""
        for mp in self.processes:
            ret = mp.process.poll()
            if ret is not None:
                logger.error("Child process %s exited prematurely with code %d", mp.name, ret)

    def terminate_all(self, timeout_s: float = 3.0) -> None:
        """Gracefully terminate only processes started and owned by this launcher."""
        logger.info("Terminating all owned demo subprocesses...")
        for mp in reversed(self.processes):
            if mp.process.poll() is None:
                try:
                    mp.process.terminate()
                except OSError:
                    pass

        # Wait for termination
        deadline = time.monotonic() + timeout_s
        for mp in self.processes:
            rem = max(0.1, deadline - time.monotonic())
            try:
                mp.process.wait(timeout=rem)
            except subprocess.TimeoutExpired:
                logger.warning("Child process %s did not terminate in time; killing...", mp.name)
                try:
                    mp.process.kill()
                    mp.process.wait(timeout=1.0)
                except OSError:
                    pass
        self.processes.clear()
        logger.info("All owned processes terminated.")

    def run_forever(self) -> None:
        """Keep demo running until interrupted by user (Ctrl+C)."""
        logger.info("Demo is running. Dashboard: http://%s:%d/web/index.html (or http://%s:%d/)", self.config.http_host, self.config.http_port, self.config.http_host, self.config.http_port)
        logger.info("Press Ctrl+C to stop all demo processes.")
        try:
            while True:
                # Monitor health of subprocesses
                for mp in self.processes:
                    ret = mp.process.poll()
                    if ret is not None:
                        raise RuntimeError(f"Child process {mp.name} exited unexpectedly (code {ret})")
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received.")
        finally:
            self.terminate_all()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NetBalance portable demo launcher")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/default.json"),
        help="Path to configuration JSON (default: configs/default.json)",
    )
    parser.add_argument(
        "--profile",
        choices=["uniform", "slow-server", "capacity"],
        default="uniform",
        help="Scenario/profile preset for backends (default: uniform)",
    )
    return parser


def main(args: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_parser()
    parsed = parser.parse_args(args)

    config = load_config(parsed.config)
    launcher = DemoLauncher(config=config, profile=parsed.profile)

    try:
        launcher.start()
        launcher.run_forever()
    except Exception as exc:
        logger.error("Launcher error: %s", exc)
        launcher.terminate_all()
        sys.exit(1)


if __name__ == "__main__":
    main()
