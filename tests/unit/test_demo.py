"""Unit and integration tests for portable demo launcher."""

from __future__ import annotations

import asyncio
import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from netbalance.config import AppConfig, BackendConfig
from netbalance.demo import DemoLauncher, PROFILE_PRESETS, is_port_in_use, wait_for_port


def test_profile_presets_exist() -> None:
    assert "uniform" in PROFILE_PRESETS
    assert "slow-server" in PROFILE_PRESETS
    assert "capacity" in PROFILE_PRESETS
    assert PROFILE_PRESETS["slow-server"]["s2"]["service_ms"] == 200.0
    assert PROFILE_PRESETS["capacity"]["s1"]["capacity"] == 5
    assert PROFILE_PRESETS["capacity"]["s2"]["capacity"] == 3
    assert PROFILE_PRESETS["capacity"]["s3"]["capacity"] == 2


def test_is_port_in_use_detects_open_and_closed_ports() -> None:
    # Closed ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # S is closed now, so port should not be in use
    assert not is_port_in_use("127.0.0.1", port)

    # Active listening port
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    listen_port = srv.getsockname()[1]
    try:
        assert is_port_in_use("127.0.0.1", listen_port)
    finally:
        srv.close()


def test_launcher_verifies_ports_and_raises_if_occupied() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    config = AppConfig(
        listen_host="127.0.0.1",
        listen_port=port,  # Occupied!
        http_host="127.0.0.1",
        http_port=8001,
        algorithm="rr",
        max_inflight=10,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.5,
        backend_timeout_s=1.0,
        workload_timeout_s=2.0,
        health_interval_s=0.1,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(BackendConfig("s1", "127.0.0.1", 9101, 1),),
    )

    try:
        launcher = DemoLauncher(config=config)
        with pytest.raises(RuntimeError, match="already in use"):
            launcher.verify_ports_available()
    finally:
        srv.close()


def test_launcher_cleanup_terminates_only_owned_processes() -> None:
    config = AppConfig(
        listen_host="127.0.0.1",
        listen_port=9000,
        http_host="127.0.0.1",
        http_port=8000,
        algorithm="rr",
        max_inflight=10,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.5,
        backend_timeout_s=1.0,
        workload_timeout_s=2.0,
        health_interval_s=0.1,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(
            BackendConfig("s1", "127.0.0.1", 9101, 1),
            BackendConfig("s2", "127.0.0.1", 9102, 1),
            BackendConfig("s3", "127.0.0.1", 9103, 1),
        ),
    )
    launcher = DemoLauncher(config=config)
    mock_p1 = MagicMock()
    mock_p1.poll.return_value = None
    mock_p2 = MagicMock()
    mock_p2.poll.return_value = None

    launcher.processes.append(MagicMock(name="p1", process=mock_p1))
    launcher.processes.append(MagicMock(name="p2", process=mock_p2))

    launcher.terminate_all()
    assert mock_p1.terminate.called
    assert mock_p2.terminate.called
    assert len(launcher.processes) == 0


def test_launcher_does_not_leave_child_output_in_unread_pipes() -> None:
    config = AppConfig(
        listen_host="127.0.0.1",
        listen_port=9000,
        http_host="127.0.0.1",
        http_port=8000,
        algorithm="rr",
        max_inflight=10,
        client_frame_timeout_s=0.5,
        backend_connect_timeout_s=0.5,
        backend_timeout_s=1.0,
        workload_timeout_s=2.0,
        health_interval_s=0.1,
        health_timeout_s=0.1,
        fail_threshold=2,
        recover_threshold=2,
        backends=(BackendConfig("s1", "127.0.0.1", 9101, 1),),
    )
    child = MagicMock()
    child.poll.return_value = None
    with (
        patch.object(DemoLauncher, "verify_ports_available"),
        patch("netbalance.demo.wait_for_port", return_value=True),
        patch("netbalance.demo.subprocess.Popen", return_value=child) as popen,
    ):
        launcher = DemoLauncher(config)
        launcher.start()
        assert len(popen.call_args_list) == 2
        assert all(call.kwargs["stdout"] is not subprocess.PIPE for call in popen.call_args_list)
        assert all(call.kwargs["stderr"] is not subprocess.PIPE for call in popen.call_args_list)
        launcher.terminate_all()
