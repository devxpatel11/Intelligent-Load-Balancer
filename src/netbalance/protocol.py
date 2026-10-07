"""Shared newline-delimited JSON protocol helpers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

MAX_FRAME_BYTES = 65_536
MAX_ID_CHARS = 64
MAX_PAYLOAD_BYTES = 1_024


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str, request_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def encode_message(message: Mapping[str, Any]) -> bytes:
    try:
        frame = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise ProtocolError("INVALID_REQUEST", "message is not JSON serializable") from exc
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError("FRAME_TOO_LARGE", "encoded frame exceeds 65,536 bytes")
    return frame


async def read_message(
    reader: asyncio.StreamReader,
    timeout_s: float,
    *,
    timeout_code: str = "CLIENT_READ_TIMEOUT",
    invalid_code: str = "INVALID_REQUEST",
) -> dict[str, Any]:
    try:
        frame = await asyncio.wait_for(reader.readuntil(b"\n"), timeout_s)
    except TimeoutError as exc:
        raise ProtocolError(timeout_code, "timed out waiting for a complete frame") from exc
    except asyncio.LimitOverrunError as exc:
        raise ProtocolError("FRAME_TOO_LARGE", "frame exceeds 65,536 bytes") from exc
    except asyncio.IncompleteReadError as exc:
        if len(exc.partial) >= MAX_FRAME_BYTES:
            raise ProtocolError("FRAME_TOO_LARGE", "frame exceeds 65,536 bytes") from exc
        raise ProtocolError(invalid_code, "connection closed before newline terminator") from exc
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError("FRAME_TOO_LARGE", "frame exceeds 65,536 bytes")
    try:
        message = json.loads(frame[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(invalid_code, "frame must contain one UTF-8 JSON object") from exc
    if not isinstance(message, dict):
        raise ProtocolError(invalid_code, "JSON message must be an object")
    return message


def _request_id(message: Mapping[str, Any]) -> str:
    request_id = message.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > MAX_ID_CHARS:
        raise ProtocolError("INVALID_REQUEST", "id must be a nonempty string of at most 64 characters")
    return request_id


def validate_work(message: Mapping[str, Any]) -> dict[str, Any]:
    request_id = _request_id(message)
    if message.get("op") != "work":
        raise ProtocolError("INVALID_REQUEST", "op must be work", request_id)
    work_units = message.get("work_units")
    if isinstance(work_units, bool) or not isinstance(work_units, int) or not 1 <= work_units <= 10:
        raise ProtocolError("INVALID_REQUEST", "work_units must be an integer from 1 through 10", request_id)
    payload = message.get("payload")
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ProtocolError("INVALID_REQUEST", "payload must be a string of at most 1,024 UTF-8 bytes", request_id)
    return {"id": request_id, "op": "work", "work_units": work_units, "payload": payload}


def validate_health(message: Mapping[str, Any]) -> dict[str, str]:
    request_id = _request_id(message)
    if message.get("op") != "health":
        raise ProtocolError("INVALID_REQUEST", "op must be health", request_id)
    return {"id": request_id, "op": "health"}


def validate_backend_response(
    message: Mapping[str, Any], request_id: str, backend_id: str, expected_echo: str | None = None
) -> bool:
    if message.get("id") != request_id or message.get("backend_id") != backend_id:
        raise ProtocolError("BACKEND_PROTOCOL_ERROR", "backend response identity does not match the assignment")
    if message.get("ok") is True:
        if not isinstance(message.get("echo"), str):
            raise ProtocolError("BACKEND_PROTOCOL_ERROR", "successful backend response requires string echo")
        if expected_echo is not None and message["echo"] != expected_echo:
            raise ProtocolError("BACKEND_PROTOCOL_ERROR", "backend response echo does not match the request")
        return True
    error = message.get("error")
    if message.get("ok") is not False or not isinstance(error, dict):
        raise ProtocolError("BACKEND_PROTOCOL_ERROR", "backend response has an invalid outcome")
    if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
        raise ProtocolError("BACKEND_PROTOCOL_ERROR", "backend error requires code and message")
    return False


def error_response(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    backend_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": request_id,
        "ok": False,
        "backend_id": backend_id,
        "error": {"code": code, "message": message},
    }
