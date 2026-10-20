"""The narrow per-agent daily series the rules evaluate (PRP-15 delta D1).

``RecommendationCompute`` and ``TelemetryAnalytics`` cannot group by agent, so the rules read this
protocol instead. A production implementation needs an agent dimension on the PRP-11 contract and
is recorded OPEN; ``SandboxSeriesSource`` (``sandbox_source.py``) is the one implementation.

Unknown is not zero. Every numeric field is ``None`` when it was not observed. ``covered`` says
whether telemetry for the agent's source was observed on that day at all: an agent with zero
events on a covered day genuinely had no usage; on an uncovered day we know nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

MAX_DURATION_SAMPLES_PER_DAY = 256


def bound_durations(values: Iterable[int]) -> tuple[int, ...]:
    """Sorted durations, deterministically thinned to ``MAX_DURATION_SAMPLES_PER_DAY`` evenly
    spaced order statistics (distribution shape kept, memory bounded)."""
    ordered = sorted(values)
    n = len(ordered)
    if n <= MAX_DURATION_SAMPLES_PER_DAY:
        return tuple(ordered)
    cap = MAX_DURATION_SAMPLES_PER_DAY
    return tuple(ordered[(i * (n - 1)) // (cap - 1)] for i in range(cap))


@dataclass(frozen=True, slots=True)
class AgentDay:
    day: date
    covered: bool
    event_count: int | None = None
    request_count: int | None = None
    error_count: int | None = None
    latency_p95_ms: float | None = None
    latency_p50_ms: float | None = None
    cost_amount: Decimal | None = None
    # Request-span durations (ms) observed on the day, sorted ascending, at most
    # ``MAX_DURATION_SAMPLES_PER_DAY`` (a deterministic quantile thinning when more were seen).
    # ``None`` = not observed. The pooled-window latency rule merges these across days.
    durations_ms: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class AgentSeries:
    agent_id: str
    cloud: str
    customer_id: str
    domain_id: str
    source: str
    lifecycle_status: str
    created_on: date | None = None
    owner_id: str | None = None
    days: tuple[AgentDay, ...] = field(default_factory=tuple)


@runtime_checkable
class AgentSeriesSource(Protocol):
    def series(
        self,
        *,
        cloud: str,
        customer_id: str,
        domain_ids: frozenset[str],
        start: date,
        end: date,
    ) -> Iterable[AgentSeries]:
        """Series for agents in the cloud, customer and domains, one entry per day in
        ``[start, end)``. Days with no information are omitted or ``covered=False``."""
        raise NotImplementedError
