from collections import Counter

from netbalance.selectors import Candidate, SelectorState, select


def candidates(active: tuple[int, int, int] = (0, 0, 0), weights: tuple[int, int, int] = (1, 1, 1)):
    return [
        Candidate(backend_id, weight, count)
        for backend_id, weight, count in zip(("s1", "s2", "s3"), weights, active, strict=True)
    ]


def test_round_robin_is_even_and_skips_ineligible() -> None:
    state = SelectorState()
    assert Counter(select(candidates(), state, "rr") for _ in range(30)) == {"s1": 10, "s2": 10, "s3": 10}
    eligible = [Candidate("s1", 1, 0), Candidate("s3", 1, 0)]
    assert [select(eligible, state, "rr") for _ in range(4)] == ["s1", "s3", "s1", "s3"]


def test_least_connections_selects_minimum_and_rotates_ties() -> None:
    state = SelectorState()
    assert select(candidates((5, 1, 3)), state, "lc") == "s2"
    state.reset()
    assert [select(candidates(), state, "lc") for _ in range(6)] == ["s1", "s2", "s3", "s1", "s2", "s3"]


def test_swrr_distribution_and_membership_reset() -> None:
    state = SelectorState()
    weighted = candidates(weights=(5, 3, 2))
    assert Counter(select(weighted, state, "swrr") for _ in range(100)) == {"s1": 50, "s2": 30, "s3": 20}
    without_s1 = weighted[1:]
    assert Counter(select(without_s1, state, "swrr") for _ in range(5)) == {"s2": 3, "s3": 2}


def test_no_eligible_backend_and_bad_policy() -> None:
    state = SelectorState()
    assert select([], state, "rr") is None
    try:
        select(candidates(), state, "random")  # type: ignore[arg-type]
    except ValueError as error:
        assert "unsupported policy" in str(error)
    else:
        raise AssertionError("unsupported policy was accepted")
