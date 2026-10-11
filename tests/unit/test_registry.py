import asyncio

import pytest

from netbalance.config import BackendConfig
from netbalance.registry import Registry


def make_registry(policy: str = "rr") -> Registry:
    backends = tuple(BackendConfig(f"s{index}", "127.0.0.1", 9100 + index, 1) for index in range(1, 4))
    return Registry(backends, policy, fail_threshold=2, recover_threshold=2)


def test_registry_rejects_invalid_backend_contract() -> None:
    with pytest.raises(ValueError, match="weights"):
        Registry(
            (BackendConfig("s1", "127.0.0.1", 9101, 0),),
            "rr",
            fail_threshold=2,
            recover_threshold=2,
        )


async def make_healthy(registry: Registry) -> None:
    for backend_id in ("s1", "s2", "s3"):
        assert await registry.record_probe(backend_id, success=True) is False
        assert await registry.record_probe(backend_id, success=True) is True


@pytest.mark.asyncio
async def test_unknown_backends_are_excluded_and_probe_thresholds_transition() -> None:
    registry = make_registry()
    assert await registry.reserve() is None
    await make_healthy(registry)
    snapshot = await registry.snapshot()
    assert [backend["health"] for backend in snapshot["backends"]] == ["healthy"] * 3


@pytest.mark.asyncio
async def test_reserve_release_is_atomic_and_exactly_once() -> None:
    registry = make_registry("lc")
    await make_healthy(registry)
    reservations = await asyncio.gather(*(registry.reserve() for _ in range(3)))
    assert {reservation.backend_id for reservation in reservations if reservation} == {"s1", "s2", "s3"}
    for reservation in reservations:
        assert reservation is not None
        await registry.release(reservation, success=True)
    with pytest.raises(RuntimeError, match="already released"):
        await registry.release(reservations[0], success=True)  # type: ignore[arg-type]
    snapshot = await registry.snapshot()
    assert all(backend["active"] == 0 for backend in snapshot["backends"])
    assert sum(backend["successes"] for backend in snapshot["backends"]) == 3


@pytest.mark.asyncio
async def test_policy_and_weight_changes_reset_state_and_increment_revision() -> None:
    registry = make_registry()
    await registry.set_algorithm("swrr")
    await registry.set_weights({"s1": 5, "s2": 3, "s3": 2})
    snapshot = await registry.snapshot()
    assert snapshot["algorithm"] == "swrr"
    assert snapshot["config_revision"] == 2
    assert [backend["weight"] for backend in snapshot["backends"]] == [5, 3, 2]
