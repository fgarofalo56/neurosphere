import pytest
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_workers.runtime import BackoffPolicy, retry_with_backoff


class Recorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


def _flaky(failures: int):
    calls = {"n": 0}

    async def op() -> str:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise DependencyTransientError("down")
        return "ok"

    return op, calls


async def test_exponential_delays_with_max_jitter() -> None:
    rec = Recorder()
    policy = BackoffPolicy(base_delay_seconds=1, max_delay_seconds=5, max_attempts=5)
    op, calls = _flaky(4)
    assert await retry_with_backoff(op, policy, sleep=rec.sleep, rng=lambda: 1.0) == "ok"
    assert rec.delays == [1, 2, 4, 5]  # capped at max_delay
    assert calls["n"] == 5


async def test_jitter_scales_delay() -> None:
    rec = Recorder()
    policy = BackoffPolicy(base_delay_seconds=2, max_attempts=3)
    op, _ = _flaky(2)
    await retry_with_backoff(op, policy, sleep=rec.sleep, rng=lambda: 0.5)
    assert rec.delays == [1.0, 2.0]


async def test_budget_exhaustion_surfaces_dependency_transient() -> None:
    rec = Recorder()
    policy = BackoffPolicy(max_attempts=3)
    op, calls = _flaky(100)
    with pytest.raises(DependencyTransientError) as info:
        await retry_with_backoff(op, policy, sleep=rec.sleep, rng=lambda: 0.0)
    assert calls["n"] == 3  # bounded, no unbounded retry
    assert len(rec.delays) == 2  # no sleep after the final failure
    assert info.value.reason == "retry_budget_exhausted"
    assert isinstance(info.value.__cause__, DependencyTransientError)


async def test_non_transient_errors_are_not_retried() -> None:
    calls = {"n": 0}

    async def op() -> None:
        calls["n"] += 1
        raise InvalidSchemaError("bad")

    with pytest.raises(InvalidSchemaError):
        await retry_with_backoff(op, BackoffPolicy(), sleep=Recorder().sleep, rng=lambda: 0.0)
    assert calls["n"] == 1


async def test_single_attempt_policy_does_not_sleep() -> None:
    rec = Recorder()
    op, _ = _flaky(1)
    with pytest.raises(DependencyTransientError):
        await retry_with_backoff(op, BackoffPolicy(max_attempts=1), sleep=rec.sleep)
    assert rec.delays == []
