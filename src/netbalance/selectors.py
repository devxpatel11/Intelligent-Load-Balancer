"""Deterministic backend selection policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

Policy = Literal["rr", "lc", "swrr"]


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    weight: int
    active: int


@dataclass(slots=True)
class SelectorState:
    signature: tuple[str, tuple[tuple[str, int], ...]] | None = None
    rr_cursor: int = 0
    lc_cursor: int = 0
    swrr_current: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.signature = None
        self.rr_cursor = 0
        self.lc_cursor = 0
        self.swrr_current.clear()


def select(eligible: Sequence[Candidate], state: SelectorState, policy: Policy) -> str | None:
    if policy not in {"rr", "lc", "swrr"}:
        raise ValueError(f"unsupported policy: {policy}")
    candidates = sorted(eligible, key=lambda candidate: candidate.id)
    if not candidates:
        state.reset()
        return None
    signature = (policy, tuple((candidate.id, candidate.weight) for candidate in candidates))
    if state.signature != signature:
        state.reset()
        state.signature = signature

    if policy == "rr":
        selected = candidates[state.rr_cursor % len(candidates)]
        state.rr_cursor += 1
        return selected.id
    if policy == "lc":
        minimum = min(candidate.active for candidate in candidates)
        tied = [candidate for candidate in candidates if candidate.active == minimum]
        selected = tied[state.lc_cursor % len(tied)]
        state.lc_cursor += 1
        return selected.id

    total_weight = sum(candidate.weight for candidate in candidates)
    for candidate in candidates:
        state.swrr_current[candidate.id] = state.swrr_current.get(candidate.id, 0) + candidate.weight
    selected = min(candidates, key=lambda candidate: (-state.swrr_current[candidate.id], candidate.id))
    state.swrr_current[selected.id] -= total_weight
    return selected.id
