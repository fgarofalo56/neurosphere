"""Exponential backoff with full jitter and a bounded retry budget."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from neurosphere_core.errors import DependencyTransientError
from pydantic import BaseModel, ConfigDict, Field

Sleep = Callable[[float], Awaitable[None]]
Random = Callable[[], float]


class BackoffPolicy(BaseModel):
    """``max_attempts`` is the total number of tries (first try included)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_delay_seconds: float = Field(default=0.5, gt=0)
    max_delay_seconds: float = Field(default=30.0, gt=0)
    multiplier: float = Field(default=2.0, ge=1.0)
    max_attempts: int = Field(default=5, ge=1)

    def delay_ceiling(self, retry_index: int) -> float:
        """Upper bound of the jitter window before retry number ``retry_index`` (0-based)."""
        return min(self.max_delay_seconds, self.base_delay_seconds * self.multiplier**retry_index)


def compute_delay(policy: BackoffPolicy, retry_index: int, rng: Random) -> float:
    """Full jitter: uniform in ``[0, ceiling]``."""
    return policy.delay_ceiling(retry_index) * rng()


async def retry_with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    policy: BackoffPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    rng: Random = random.random,  # jitter only, not security sensitive
) -> T:
    """Run ``operation``, retrying ``DependencyTransientError`` within the budget.

    After ``max_attempts`` failures a ``DependencyTransientError`` (reason
    ``retry_budget_exhausted``) is raised, chained from the last failure. Any other
    exception propagates immediately.
    """
    last: DependencyTransientError | None = None
    for attempt in range(policy.max_attempts):
        try:
            return await operation()
        except DependencyTransientError as exc:
            last = exc
            if attempt + 1 < policy.max_attempts:
                await sleep(compute_delay(policy, attempt, rng))
    raise DependencyTransientError(
        f"retry budget exhausted after {policy.max_attempts} attempts",
        reason="retry_budget_exhausted",
    ) from last
