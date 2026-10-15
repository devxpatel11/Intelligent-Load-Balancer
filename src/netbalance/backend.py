"""Backend server for the Intelligent Network Load Balancer.

Implements the frozen newline-delimited JSON TCP protocol for work and health requests
according to docs/contracts.md and docs/protocol.md, using shared helpers from
netbalance.protocol.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import math
import signal
import sys
from collections.abc import Mapping
from typing import Any, Optional

from netbalance.protocol import (
    MAX_FRAME_BYTES,
    MAX_ID_CHARS,
    ProtocolError,
    encode_message,
    error_response,
    read_message,
    validate_health,
    validate_work,
)

CLIENT_READ_TIMEOUT_S = 2.0

logger = logging.getLogger("netbalance.backend")


def encode_json_frame(data: Mapping[str, Any]) -> bytes:
    """Serialize dictionary as compact UTF-8 JSON followed by newline using A1 helper."""
    return encode_message(data)


class BackendServer:
    """Asynchronous backend worker server."""

    def __init__(
        self,
        backend_id: str,
        host: str = "127.0.0.1",
        port: int = 9101,
        service_ms: float = 50.0,
        capacity: int = 4,
    ) -> None:
        if not backend_id or not isinstance(backend_id, str):
            raise ValueError("backend_id must be a non-empty string")
        if not isinstance(host, str) or not host:
            raise ValueError("host must be a non-empty string")
        if isinstance(port, bool) or not isinstance(port, int) or not (0 <= port <= 65535):
            raise ValueError(f"port must be an integer between 0 and 65535, got {port}")
        if (
            isinstance(service_ms, bool)
            or not isinstance(service_ms, (int, float))
            or not math.isfinite(service_ms)
            or service_ms < 0
        ):
            raise ValueError(
                f"service_ms must be a finite, nonnegative number, got {service_ms}"
            )
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError(f"capacity must be a positive integer, got {capacity}")

        self.backend_id = backend_id
        self.host = host
        self.port = port
        self.service_ms = float(service_ms)
        self.capacity = capacity

        self._server: Optional[asyncio.Server] = None
        self._work_semaphore = asyncio.Semaphore(self.capacity)
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._active_writers: set[asyncio.StreamWriter] = set()

    @property
    def bound_port(self) -> int:
        """Return the actual bound port of the server sockets."""
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self.port

    @property
    def active_work_count(self) -> int:
        """Number of work slots currently occupied."""
        return self.capacity - self._work_semaphore._value

    async def start(self) -> None:
        """Start listening for incoming TCP connections."""
        if self._server is not None:
            raise RuntimeError("backend is already running")
        self._server = await asyncio.start_server(
            self._handle_client_connection,
            host=self.host,
            port=self.port,
            limit=MAX_FRAME_BYTES,
        )
        logger.info(
            "[%s] Backend %s listening on %s:%d (service_ms=%.1f, capacity=%d)",
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            self.backend_id,
            self.host,
            self.bound_port,
            self.service_ms,
            self.capacity,
        )

    async def stop(self) -> None:
        """Gracefully stop server, close sockets, and cleanup all active connections."""
        server = self._server
        if self._server is not None:
            self._server.close()
            self._server = None

        # Cancel and close active client connections
        for writer in list(self._active_writers):
            try:
                writer.close()
            except Exception:
                pass

        if self._active_tasks:
            for task in list(self._active_tasks):
                task.cancel()
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            self._active_tasks.clear()

        if server is not None:
            await server.wait_closed()

        for writer in list(self._active_writers):
            try:
                await writer.wait_closed()
            except Exception:
                pass
        self._active_writers.clear()

        logger.info(
            "[%s] Backend %s stopped and ports freed",
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            self.backend_id,
        )

    async def serve_forever(self) -> None:
        """Run the server until interrupted."""
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    def _handle_client_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Dispatch a single client connection to an owned background task."""
        self._active_writers.add(writer)
        task = asyncio.create_task(self._process_connection(reader, writer))
        self._active_tasks.add(task)

        def _cleanup(_: asyncio.Task[None]) -> None:
            self._active_tasks.discard(task)
            self._active_writers.discard(writer)

        task.add_done_callback(_cleanup)

    def _validate_request(self, payload_dict: Any) -> dict[str, Any]:
        """Strictly validate incoming parsed JSON request object using protocol helpers."""
        if not isinstance(payload_dict, dict):
            raise ProtocolError("INVALID_REQUEST", "request must be a JSON object")

        op = payload_dict.get("op")
        if op == "health":
            return validate_health(payload_dict)
        elif op == "work":
            return validate_work(payload_dict)
        else:
            raw_id = payload_dict.get("id")
            req_id = raw_id if isinstance(raw_id, str) and len(raw_id) <= MAX_ID_CHARS else None
            raise ProtocolError(
                "INVALID_REQUEST",
                f"unsupported operation '{op}'",
                request_id=req_id,
            )

    async def _process_work(self, work_units: int) -> None:
        """Simulate work processing under concurrency limit."""
        duration_s = (self.service_ms * work_units) / 1000.0
        async with self._work_semaphore:
            if duration_s > 0:
                await asyncio.sleep(duration_s)

    async def _process_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Process exactly one request and send one response before closing."""
        extracted_id: Optional[str] = None
        now_ts = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            # Read complete newline-delimited frame within deadline using A1 protocol helper
            message = await read_message(
                reader,
                timeout_s=CLIENT_READ_TIMEOUT_S,
                timeout_code="CLIENT_READ_TIMEOUT",
                invalid_code="INVALID_REQUEST",
            )

            if isinstance(message, dict) and isinstance(message.get("id"), str):
                raw_id = message["id"]
                if raw_id and len(raw_id) <= MAX_ID_CHARS and not isinstance(raw_id, bool):
                    extracted_id = raw_id

            validated = self._validate_request(message)
            extracted_id = validated["id"]
            op = validated["op"]

            logger.info(
                "[%s] Backend %s received request id=%s op=%s",
                now_ts(),
                self.backend_id,
                extracted_id,
                op,
            )

            if op == "health":
                response_data = {
                    "id": validated["id"],
                    "ok": True,
                    "backend_id": self.backend_id,
                    "status": "healthy",
                }
            else:
                work_units = validated["work_units"]
                payload = validated["payload"]
                await self._process_work(work_units)
                response_data = {
                    "id": validated["id"],
                    "ok": True,
                    "backend_id": self.backend_id,
                    "echo": payload,
                }

            response_bytes = encode_message(response_data)
            writer.write(response_bytes)
            await writer.drain()

            logger.info(
                "[%s] Backend %s finished request id=%s op=%s ok=True",
                now_ts(),
                self.backend_id,
                extracted_id,
                op,
            )

        except ProtocolError as err:
            req_id = err.request_id if err.request_id is not None else extracted_id
            logger.warning(
                "[%s] Backend %s protocol error for request id=%s: code=%s message=%s",
                now_ts(),
                self.backend_id,
                req_id,
                err.code,
                err.message,
            )
            err_dict = error_response(
                code=err.code,
                message=err.message,
                request_id=req_id,
                backend_id=self.backend_id,
            )
            try:
                writer.write(encode_message(err_dict))
                await writer.drain()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            except Exception:
                pass
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, EOFError) as exc:
            logger.debug(
                "[%s] Backend %s client disconnected early: %s",
                now_ts(),
                self.backend_id,
                exc,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "[%s] Unexpected error in backend %s: %s",
                now_ts(),
                self.backend_id,
                exc,
            )
            err_dict = error_response(
                code="INVALID_REQUEST",
                message="internal server error",
                request_id=extracted_id,
                backend_id=self.backend_id,
            )
            try:
                writer.write(encode_message(err_dict))
                await writer.drain()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            except Exception:
                pass


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for backend service."""
    parser = argparse.ArgumentParser(
        description="Intelligent Load Balancer Backend Worker",
        prog="python -m netbalance.backend",
    )
    parser.add_argument("--id", required=True, help="Unique backend identifier (e.g. s1)")
    parser.add_argument("--port", type=int, required=True, help="TCP port to listen on")
    parser.add_argument(
        "--service-ms",
        type=float,
        default=50.0,
        help="Base service time in milliseconds (default: 50.0)",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=4,
        help="Maximum concurrent work requests (default: 4)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)",
    )
    return parser.parse_args(args)


async def amain(args: Optional[list[str]] = None) -> None:
    """Async CLI entry point."""
    parsed = parse_args(args)
    server = BackendServer(
        backend_id=parsed.id,
        host=parsed.host,
        port=parsed.port,
        service_ms=parsed.service_ms,
        capacity=parsed.capacity,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Signals not fully supported on Windows event loops
            pass

    await server.start()
    try:
        if sys.platform == "win32":
            # Polling wait on Windows to allow KeyboardInterrupt
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
        else:
            await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()


def main() -> None:
    """Synchronous entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
