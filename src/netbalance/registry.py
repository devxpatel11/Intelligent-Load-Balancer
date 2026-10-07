"""Atomic backend state, selection, and reservation accounting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from typing import Literal, cast

from .config import BackendConfig
from .selectors import Candidate, Policy, SelectorState, select

Health = Literal["unknown", "healthy", "unhealthy"]


@dataclass(slots=True)
class _Backend:
    config: BackendConfig
    health: Health = "unknown"
    active: int = 0
    assignments: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_probe_successes: int = 0
    consecutive_probe_failures: int = 0
    last_transition_at: str | None = None


@dataclass(frozen=True, slots=True)
class Reservation:
    token: int
    backend_id: str
    host: str
    port: int


class Registry:
    def __init__(
        self,
        backends: tuple[BackendConfig, ...],
        algorithm: str,
        *,
        fail_threshold: int,
        recover_threshold: int,
    ) -> None:
        if algorithm not in {"rr", "lc", "swrr"}:
            raise ValueError("algorithm must be rr, lc, or swrr")
        if not backends:
            raise ValueError("at least one backend is required")
        if any(
            not backend.id
            or not backend.host
            or isinstance(backend.port, bool)
            or not 1 <= backend.port <= 65_535
            or isinstance(backend.weight, bool)
            or not 1 <= backend.weight <= 100
            for backend in backends
        ):
            raise ValueError("backends require nonempty IDs/hosts, valid ports, and weights from 1 through 100")
        if len({backend.port for backend in backends}) != len(backends):
            raise ValueError("backend ports must be unique")
        if fail_threshold < 1 or recover_threshold < 1:
            raise ValueError("probe thresholds must be positive")
        self._backends = {backend.id: _Backend(backend) for backend in backends}
        if len(self._backends) != len(backends):
            raise ValueError("backend IDs must be unique")
        self._algorithm = cast(Policy, algorithm)
        self._fail_threshold = fail_threshold
        self._recover_threshold = recover_threshold
        self._selector = SelectorState()
        self._lock = asyncio.Lock()
        self._token_counter = count(1)
        self._reservations: dict[int, str] = {}
        self._config_revision = 0

    async def reserve(self) -> Reservation | None:
        async with self._lock:
            eligible = [
                Candidate(backend.config.id, backend.config.weight, backend.active)
                for backend in self._backends.values()
                if backend.health == "healthy"
            ]
            backend_id = select(eligible, self._selector, self._algorithm)
            if backend_id is None:
                return None
            backend = self._backends[backend_id]
            backend.active += 1
            backend.assignments += 1
            token = next(self._token_counter)
            self._reservations[token] = backend_id
            return Reservation(token, backend_id, backend.config.host, backend.config.port)

    async def release(self, reservation: Reservation, *, success: bool) -> None:
        async with self._lock:
            backend_id = self._reservations.pop(reservation.token, None)
            if backend_id != reservation.backend_id:
                raise RuntimeError("reservation is unknown or already released")
            backend = self._backends[backend_id]
            if backend.active <= 0:
                raise RuntimeError("backend active count invariant violated")
            backend.active -= 1
            if success:
                backend.successes += 1
            else:
                backend.failures += 1

    async def record_probe(self, backend_id: str, *, success: bool) -> bool:
        async with self._lock:
            backend = self._backend(backend_id)
            old_health = backend.health
            if success:
                backend.consecutive_probe_successes += 1
                backend.consecutive_probe_failures = 0
                if backend.health != "healthy" and backend.consecutive_probe_successes >= self._recover_threshold:
                    backend.health = "healthy"
            else:
                backend.consecutive_probe_failures += 1
                backend.consecutive_probe_successes = 0
                if backend.health != "unhealthy" and backend.consecutive_probe_failures >= self._fail_threshold:
                    backend.health = "unhealthy"
            if backend.health == old_health:
                return False
            backend.last_transition_at = datetime.now(timezone.utc).isoformat()
            self._selector.reset()
            return True

    async def set_algorithm(self, algorithm: str) -> None:
        if algorithm not in {"rr", "lc", "swrr"}:
            raise ValueError("algorithm must be rr, lc, or swrr")
        async with self._lock:
            if self._algorithm != algorithm:
                self._algorithm = cast(Policy, algorithm)
                self._selector.reset()
                self._config_revision += 1

    async def set_weights(self, weights: dict[str, int]) -> None:
        if set(weights) != set(self._backends):
            raise ValueError("weights must contain every configured backend ID")
        if any(isinstance(weight, bool) or not isinstance(weight, int) or not 1 <= weight <= 100 for weight in weights.values()):
            raise ValueError("weights must be integers from 1 through 100")
        async with self._lock:
            changed = False
            for backend_id, weight in weights.items():
                backend = self._backends[backend_id]
                if backend.config.weight != weight:
                    backend.config = BackendConfig(backend.config.id, backend.config.host, backend.config.port, weight)
                    changed = True
            if changed:
                self._selector.reset()
                self._config_revision += 1

    async def reset_statistics(self) -> None:
        async with self._lock:
            if self._reservations:
                raise RuntimeError("cannot reset while work is active")
            for backend in self._backends.values():
                backend.assignments = backend.successes = backend.failures = 0
            self._selector.reset()

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            return {
                "algorithm": self._algorithm,
                "config_revision": self._config_revision,
                "backends": [self._backend_snapshot(self._backends[key]) for key in sorted(self._backends)],
            }

    def _backend(self, backend_id: str) -> _Backend:
        try:
            return self._backends[backend_id]
        except KeyError as exc:
            raise ValueError(f"unknown backend ID: {backend_id}") from exc

    @staticmethod
    def _backend_snapshot(backend: _Backend) -> dict[str, object]:
        return {
            "id": backend.config.id,
            "host": backend.config.host,
            "port": backend.config.port,
            "weight": backend.config.weight,
            "health": backend.health,
            "active": backend.active,
            "assignments": backend.assignments,
            "successes": backend.successes,
            "failures": backend.failures,
            "consecutive_probe_successes": backend.consecutive_probe_successes,
            "consecutive_probe_failures": backend.consecutive_probe_failures,
            "last_transition_at": backend.last_transition_at,
        }
