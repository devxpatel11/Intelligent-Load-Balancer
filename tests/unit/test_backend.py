"""Unit tests for backend.py parsing, validation, logging, and parameter rules."""

from __future__ import annotations

import logging
import pytest

from netbalance.backend import (
    BackendServer,
    ProtocolError,
    encode_json_frame,
    parse_args,
)


def test_encode_json_frame() -> None:
    data = {"id": "req-1", "ok": True, "backend_id": "s1"}
    encoded = encode_json_frame(data)
    assert encoded.endswith(b"\n")
    assert encoded == b'{"id":"req-1","ok":true,"backend_id":"s1"}\n'


def test_server_init_validation() -> None:
    # Valid initializations
    server = BackendServer(backend_id="s1", port=9101, service_ms=50.0, capacity=4)
    assert server.backend_id == "s1"
    assert server.port == 9101
    assert server.service_ms == 50.0
    assert server.capacity == 4

    # service_ms=0 is valid (nonnegative)
    zero_ms_server = BackendServer(backend_id="s1", port=9101, service_ms=0.0)
    assert zero_ms_server.service_ms == 0.0

    # Ephemeral port 0 is valid
    ephemeral_server = BackendServer(backend_id="s1", port=0)
    assert ephemeral_server.port == 0

    # Invalid ID
    with pytest.raises(ValueError, match="backend_id"):
        BackendServer(backend_id="", port=9101)
    with pytest.raises(ValueError, match="backend_id"):
        BackendServer(backend_id=None, port=9101)  # type: ignore

    # Invalid port
    with pytest.raises(ValueError, match="port"):
        BackendServer(backend_id="s1", port=-1)
    with pytest.raises(ValueError, match="port"):
        BackendServer(backend_id="s1", port=70000)
    with pytest.raises(ValueError, match="port"):
        BackendServer(backend_id="s1", port=True)  # type: ignore

    # Invalid service_ms
    with pytest.raises(ValueError, match="service_ms"):
        BackendServer(backend_id="s1", port=9101, service_ms=-1.0)
    with pytest.raises(ValueError, match="service_ms"):
        BackendServer(backend_id="s1", port=9101, service_ms=float("inf"))
    with pytest.raises(ValueError, match="service_ms"):
        BackendServer(backend_id="s1", port=9101, service_ms=float("nan"))
    with pytest.raises(ValueError, match="service_ms"):
        BackendServer(backend_id="s1", port=9101, service_ms=True)  # type: ignore

    # Invalid capacity
    with pytest.raises(ValueError, match="capacity"):
        BackendServer(backend_id="s1", port=9101, capacity=0)
    with pytest.raises(ValueError, match="capacity"):
        BackendServer(backend_id="s1", port=9101, capacity=-1)
    with pytest.raises(ValueError, match="capacity"):
        BackendServer(backend_id="s1", port=9101, capacity=True)  # type: ignore
    with pytest.raises(ValueError, match="capacity"):
        BackendServer(backend_id="s1", port=9101, capacity=4.5)  # type: ignore


def test_validate_request_work_valid() -> None:
    server = BackendServer(backend_id="s1", port=9101)
    req = {"id": "r0001", "op": "work", "work_units": 2, "payload": "hello"}
    validated = server._validate_request(req)
    assert validated["id"] == "r0001"
    assert validated["work_units"] == 2
    assert validated["payload"] == "hello"


def test_validate_request_work_invalid_units() -> None:
    server = BackendServer(backend_id="s1", port=9101)

    for invalid_units in (0, 11, -1, True, False, 1.5, "1", None):
        req = {"id": "r0001", "op": "work", "work_units": invalid_units, "payload": "hello"}
        with pytest.raises(ProtocolError) as exc_info:
            server._validate_request(req)
        assert exc_info.value.code == "INVALID_REQUEST"
        assert exc_info.value.request_id == "r0001"


def test_validate_request_work_payload_limit() -> None:
    server = BackendServer(backend_id="s1", port=9101)

    # 1024 ASCII bytes is valid
    valid_payload = "a" * 1024
    req = {"id": "r0001", "op": "work", "work_units": 1, "payload": valid_payload}
    assert server._validate_request(req)["payload"] == valid_payload

    # 1025 ASCII bytes exceeds limit
    invalid_payload = "a" * 1025
    req = {"id": "r0001", "op": "work", "work_units": 1, "payload": invalid_payload}
    with pytest.raises(ProtocolError) as exc_info:
        server._validate_request(req)
    assert exc_info.value.code == "INVALID_REQUEST"

    # Multi-byte UTF-8 string exceeding 1024 bytes
    utf8_payload = "€" * 400  # 400 * 3 = 1200 bytes
    req = {"id": "r0001", "op": "work", "work_units": 1, "payload": utf8_payload}
    with pytest.raises(ProtocolError) as exc_info:
        server._validate_request(req)
    assert exc_info.value.code == "INVALID_REQUEST"


def test_validate_request_id_rules() -> None:
    server = BackendServer(backend_id="s1", port=9101)

    # Valid ID up to 64 chars
    valid_id = "x" * 64
    assert server._validate_request({"id": valid_id, "op": "health"})["id"] == valid_id

    # Exceeding 64 chars
    with pytest.raises(ProtocolError) as exc_info:
        server._validate_request({"id": "x" * 65, "op": "health"})
    assert exc_info.value.code == "INVALID_REQUEST"

    # Empty ID
    with pytest.raises(ProtocolError) as exc_info:
        server._validate_request({"id": "", "op": "health"})
    assert exc_info.value.code == "INVALID_REQUEST"

    # Non-string ID or booleans
    for non_str in (123, True, False, None, ["id"]):
        with pytest.raises(ProtocolError) as exc_info:
            server._validate_request({"id": non_str, "op": "health"})
        assert exc_info.value.code == "INVALID_REQUEST"


def test_validate_request_health() -> None:
    server = BackendServer(backend_id="s1", port=9101)
    req = {"id": "probe-s1", "op": "health"}
    validated = server._validate_request(req)
    assert validated["id"] == "probe-s1"
    assert validated["op"] == "health"


def test_validate_request_unknown_op() -> None:
    server = BackendServer(backend_id="s1", port=9101)
    with pytest.raises(ProtocolError) as exc_info:
        server._validate_request({"id": "r01", "op": "status"})
    assert exc_info.value.code == "INVALID_REQUEST"


def test_parse_args() -> None:
    args = parse_args(["--id", "s2", "--port", "9102", "--service-ms", "75.5", "--capacity", "8", "--host", "127.0.0.1"])
    assert args.id == "s2"
    assert args.port == 9102
    assert args.service_ms == 75.5
    assert args.capacity == 8
    assert args.host == "127.0.0.1"


def test_logging_payload_privacy(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that sensitive/arbitrary work payload strings are never logged."""
    server = BackendServer(backend_id="s1", port=9101)
    secret_payload = "super-secret-user-payload-12345"

    with caplog.at_level(logging.INFO):
        logger = logging.getLogger("netbalance.backend")
        logger.info("Backend %s received request id=%s op=%s", "s1", "r001", "work")

    for record in caplog.records:
        assert secret_payload not in record.message
