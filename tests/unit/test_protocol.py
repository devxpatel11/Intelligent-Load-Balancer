import asyncio

import pytest

from netbalance.protocol import (
    MAX_FRAME_BYTES,
    ProtocolError,
    encode_message,
    read_message,
    validate_backend_response,
    validate_health,
    validate_work,
)


@pytest.mark.asyncio
async def test_read_message_accepts_fragmented_frame() -> None:
    reader = asyncio.StreamReader(limit=MAX_FRAME_BYTES)
    result = asyncio.create_task(read_message(reader, 0.5))
    reader.feed_data(b'{"id":"r1","op":"work",')
    await asyncio.sleep(0)
    reader.feed_data(b'"work_units":1,"payload":"ok"}\n')
    assert await result == {"id": "r1", "op": "work", "work_units": 1, "payload": "ok"}


@pytest.mark.asyncio
async def test_read_message_has_a_finite_deadline() -> None:
    with pytest.raises(ProtocolError) as error:
        await read_message(asyncio.StreamReader(), 0.01)
    assert error.value.code == "CLIENT_READ_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b'{not-json}\n', "INVALID_REQUEST"),
        (b"\xff\n", "INVALID_REQUEST"),
        (b'{}', "INVALID_REQUEST"),
        (b"x" * MAX_FRAME_BYTES + b"\n", "FRAME_TOO_LARGE"),
    ],
    ids=("malformed-json", "invalid-utf8", "truncated", "oversized"),
)
async def test_read_message_rejects_invalid_frames(data: bytes, code: str) -> None:
    reader = asyncio.StreamReader(limit=MAX_FRAME_BYTES)
    reader.feed_data(data)
    reader.feed_eof()
    with pytest.raises(ProtocolError) as error:
        await read_message(reader, 0.5)
    assert error.value.code == code


def test_work_and_health_validation() -> None:
    work = {"id": "r1", "op": "work", "work_units": 2, "payload": "héllo"}
    assert validate_work(work) == work
    assert validate_health({"id": "probe-s1", "op": "health"})["op"] == "health"
    for invalid in (
        {**work, "id": ""},
        {**work, "work_units": True},
        {**work, "work_units": 11},
        {**work, "payload": "€" * 342},
    ):
        with pytest.raises(ProtocolError) as error:
            validate_work(invalid)
        assert error.value.code == "INVALID_REQUEST"


def test_encode_and_backend_response_validation() -> None:
    response = {"id": "r1", "ok": True, "backend_id": "s1", "echo": "hello"}
    assert encode_message(response).endswith(b"\n")
    assert validate_backend_response(response, "r1", "s1") is True
    with pytest.raises(ProtocolError) as error:
        validate_backend_response({**response, "backend_id": "s2"}, "r1", "s1")
    assert error.value.code == "BACKEND_PROTOCOL_ERROR"
