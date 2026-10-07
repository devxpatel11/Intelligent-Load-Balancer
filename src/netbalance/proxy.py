"""One-request-per-connection TCP proxy."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .metrics import Metrics
from .protocol import (
    MAX_FRAME_BYTES,
    ProtocolError,
    encode_message,
    error_response,
    read_message,
    validate_backend_response,
    validate_work,
)
from .registry import Registry, Reservation


@dataclass(frozen=True, slots=True)
class _Outcome:
    response: dict[str, Any]
    success: bool
    error_code: str | None


class ProxyServer:
    def __init__(self, config: AppConfig, registry: Registry, metrics: Metrics) -> None:
        self.config = config
        self.registry = registry
        self.metrics = metrics
        self._server: asyncio.Server | None = None
        self._client_tasks: set[asyncio.Task[None]] = set()

    async def start(self, *, host: str | None = None, port: int | None = None) -> None:
        if self._server is not None:
            raise RuntimeError("proxy is already running")
        self._server = await asyncio.start_server(
            self._handle_client,
            host or self.config.listen_host,
            self.config.listen_port if port is None else port,
            limit=MAX_FRAME_BYTES,
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        current = asyncio.current_task()
        tasks = [task for task in self._client_tasks if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("proxy is not running")
        host, port = self._server.sockets[0].getsockname()[:2]
        return str(host), int(port)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
        request_id: str | None = None
        reservation: Reservation | None = None
        admitted = False
        finished = False
        backend_success = False
        started = time.perf_counter()
        try:
            request = validate_work(await read_message(reader, self.config.client_frame_timeout_s))
            request_id = request["id"]
            admitted = await self.metrics.admit(request_id)
            if not admitted:
                await self._send(writer, error_response("OVERLOADED", "proxy work limit reached", request_id=request_id))
                return

            reservation = await self.registry.reserve()
            if reservation is None:
                await self.metrics.finish_failure(request_id, "NO_HEALTHY_BACKEND", rejected=True)
                finished = True
                await self._send(writer, error_response(
                    "NO_HEALTHY_BACKEND", "no backend is currently eligible", request_id=request_id
                ))
                return

            await self.metrics.assigned(request_id, reservation.backend_id)
            outcome = await self._forward(request, reservation)
            backend_success = outcome.success
            await self._send(writer, outcome.response)
            latency_ms = (time.perf_counter() - started) * 1_000
            if outcome.success:
                await self.metrics.finish_success(request_id, reservation.backend_id, latency_ms)
            else:
                await self.metrics.finish_failure(
                    request_id,
                    outcome.error_code or "BACKEND_PROTOCOL_ERROR",
                    backend_id=reservation.backend_id,
                    latency_ms=latency_ms,
                )
            finished = True
        except ProtocolError as exc:
            await self.metrics.protocol_error(exc.request_id, exc.code)
            await self._try_send(writer, error_response(exc.code, exc.message, request_id=exc.request_id))
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError):
            pass
        finally:
            if reservation is not None:
                await self.registry.release(reservation, success=backend_success)
            if admitted and not finished:
                assert request_id is not None
                await self.metrics.finish_failure(
                    request_id,
                    "BACKEND_UNAVAILABLE",
                    backend_id=reservation.backend_id if reservation else None,
                    latency_ms=(time.perf_counter() - started) * 1_000,
                )
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self._client_tasks.discard(task)

    async def _forward(self, request: dict[str, Any], reservation: Reservation) -> _Outcome:
        backend_writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self.config.backend_timeout_s):
                try:
                    backend_reader, backend_writer = await asyncio.wait_for(
                        asyncio.open_connection(
                            reservation.host,
                            reservation.port,
                            limit=MAX_FRAME_BYTES,
                        ),
                        self.config.backend_connect_timeout_s,
                    )
                except TimeoutError as exc:
                    raise ConnectionError("backend connect deadline exceeded") from exc
                backend_writer.write(encode_message(request))
                await backend_writer.drain()
                response = await read_message(
                    backend_reader,
                    self.config.backend_timeout_s,
                    timeout_code="BACKEND_TIMEOUT",
                    invalid_code="BACKEND_PROTOCOL_ERROR",
                )
                success = validate_backend_response(
                    response, request["id"], reservation.backend_id, request["payload"]
                )
                code = None if success else str(response["error"]["code"])
                return _Outcome(response, success, code)
        except TimeoutError:
            code, message = "BACKEND_TIMEOUT", "backend transaction timed out"
        except ProtocolError as exc:
            code, message = "BACKEND_PROTOCOL_ERROR", exc.message
        except (ConnectionError, OSError):
            code, message = "BACKEND_UNAVAILABLE", "could not complete the backend connection"
        finally:
            if backend_writer is not None:
                backend_writer.close()
                try:
                    await backend_writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
        return _Outcome(
            error_response(code, message, request_id=request["id"], backend_id=reservation.backend_id),
            False,
            code,
        )

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        writer.write(encode_message(message))
        await writer.drain()

    async def _try_send(self, writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        try:
            await self._send(writer, message)
        except (ConnectionError, OSError):
            pass
