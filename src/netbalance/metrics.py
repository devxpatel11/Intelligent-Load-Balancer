"""In-memory request metrics with frozen snapshot semantics."""

from __future__ import annotations

import asyncio
import math
import statistics
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import Registry


class Metrics:
    def __init__(self, max_inflight: int) -> None:
        self._max_inflight = max_inflight
        self._lock = asyncio.Lock()
        self._metrics_epoch = 0
        self._inflight = 0
        self._received = 0
        self._succeeded = 0
        self._failed = 0
        self._rejected = 0
        self._protocol_errors = 0
        self._successful_latency_ms: list[float] = []
        self._events: deque[dict[str, object]] = deque(maxlen=200)

    async def admit(self, request_id: str) -> bool:
        async with self._lock:
            self._received += 1
            if self._inflight >= self._max_inflight:
                self._failed += 1
                self._rejected += 1
                self._event(request_id, "error", None, "failed", "OVERLOADED", None)
                return False
            self._inflight += 1
            return True

    async def protocol_error(self, request_id: str | None, code: str) -> None:
        async with self._lock:
            self._protocol_errors += 1
            self._event(request_id, "error", None, "failed", code, None)

    async def assigned(self, request_id: str, backend_id: str) -> None:
        async with self._lock:
            self._event(request_id, "assign", backend_id, "inflight", None, None)

    async def finish_success(self, request_id: str, backend_id: str, latency_ms: float) -> None:
        async with self._lock:
            self._finish()
            self._succeeded += 1
            self._successful_latency_ms.append(latency_ms)
            self._event(request_id, "success", backend_id, "succeeded", None, latency_ms)

    async def finish_failure(
        self,
        request_id: str,
        code: str,
        *,
        backend_id: str | None = None,
        rejected: bool = False,
        latency_ms: float | None = None,
    ) -> None:
        async with self._lock:
            self._finish()
            self._failed += 1
            if rejected:
                self._rejected += 1
            self._event(request_id, "error", backend_id, "failed", code, latency_ms)

    async def health_transition(self, backend_id: str, health: str) -> None:
        async with self._lock:
            self._event(None, "health_transition", backend_id, health, None, None)

    async def config_change(self) -> None:
        async with self._lock:
            self._event(None, "config_change", None, "updated", None, None)

    async def reset(self, registry: Registry) -> int:
        async with self._lock:
            if self._inflight:
                raise RuntimeError("cannot reset while work is active")
            await registry.reset_statistics()
            self._metrics_epoch += 1
            self._received = self._succeeded = self._failed = self._rejected = self._protocol_errors = 0
            self._successful_latency_ms.clear()
            self._events.clear()
            self._event(None, "reset", None, "succeeded", None, None)
            return self._metrics_epoch

    async def snapshot(self, registry: dict[str, object]) -> dict[str, object]:
        async with self._lock:
            latencies = sorted(self._successful_latency_ms)
            return {
                "schema_version": 1,
                "metrics_epoch": self._metrics_epoch,
                "config_revision": registry["config_revision"],
                "algorithm": registry["algorithm"],
                "inflight": self._inflight,
                "totals": {
                    "received": self._received,
                    "succeeded": self._succeeded,
                    "failed": self._failed,
                    "rejected": self._rejected,
                    "protocol_errors": self._protocol_errors,
                },
                "successful_proxy_latency_ms": {
                    "count": len(latencies),
                    "mean": statistics.fmean(latencies) if latencies else None,
                    "p50": self._percentile(latencies, 0.50),
                    "p95": self._percentile(latencies, 0.95),
                },
                "backends": registry["backends"],
                "events": list(self._events),
            }

    def _finish(self) -> None:
        if self._inflight <= 0:
            raise RuntimeError("global inflight accounting invariant violated")
        self._inflight -= 1

    def _event(
        self,
        request_id: str | None,
        action: str,
        backend_id: str | None,
        outcome: str,
        error_code: str | None,
        latency_ms: float | None,
    ) -> None:
        self._events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": action,
            "backend_id": backend_id,
            "outcome": outcome,
            "error_code": error_code,
            "latency_ms": latency_ms,
        })

    @staticmethod
    def _percentile(values: list[float], quantile: float) -> float | None:
        return values[math.ceil(quantile * len(values)) - 1] if values else None
