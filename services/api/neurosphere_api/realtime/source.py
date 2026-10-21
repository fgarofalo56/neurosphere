"""Delta source: what the gateway pushes, read from PRP-14 hot aggregates (PRP-18 item 1).

``DeltaSource`` is a small protocol; :class:`AggregateDeltaSource` is the default and reads ONLY
``neurosphere_core.aggregates.AggregateReader`` (never raw events, the ledger or the analytics
adapter). Authorization is NOT this module's job: the gateway checks ``data.read`` on the domain
against the session's current scope before every call, and passes the customer from that scope.

The hot aggregates are domain-level rollups, so a delta carries one ``cluster`` node for the
domain with the metrics the aggregates can support (``frequency`` and ``latency_p95_ms`` from the
latest hour; ``health`` from the error rate). ``tokens`` and ``context_size`` are not aggregated
at this grain and stay ``None``. Unknown is ``None``, never 0. ``edges`` is empty: edges come from
the viewport API (item 2), not from aggregates. Coverage and lag come from the aggregate status
and document completeness; a gap is labelled, never smoothed over.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from neurosphere_core.aggregates import (
    AggregateReader,
    AggregateStatus,
    AggregateWindow,
    ErrorPoint,
    LatencyPoint,
    QueryResult,
    bucket_start,
)
from pydantic import BaseModel, ConfigDict

from neurosphere_api.realtime.settings import RealtimeSettings

__all__ = [
    "AggregateDeltaSource",
    "Coverage",
    "DeltaEdge",
    "DeltaNode",
    "DeltaPayload",
    "DeltaSource",
    "NodeMetrics",
]

Health = Literal["ok", "degraded", "failing", "unknown"]
CoverageState = Literal["complete", "partial", "delayed", "unknown"]
_CACHE_MAX_ENTRIES = 1024


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeMetrics(_Model):
    tokens: int | None = None
    context_size: int | None = None
    frequency: int | None = None
    latency_p95_ms: int | None = None
    health: Health = "unknown"


class DeltaNode(_Model):
    id: str
    kind: Literal["person", "agent", "sub_agent", "model", "source", "cluster"]
    label: str
    cluster_id: str | None = None
    member_count: int | None = None
    metrics: NodeMetrics


class DeltaEdge(_Model):
    id: str
    source: str
    target: str
    provenance: Literal["observed", "declared", "inferred"]
    last_observed_at: str | None = None


class Coverage(_Model):
    state: CoverageState
    lag_seconds: float | None = None
    as_of: str | None = None


class DeltaPayload(_Model):
    """Content of one delta before the gateway adds ``seq`` and ``emitted_at``."""

    nodes: tuple[DeltaNode, ...] = ()
    edges: tuple[DeltaEdge, ...] = ()
    coverage: Coverage

    def digest(self) -> str:
        """Change detector: everything except the lag, which grows on every tick."""
        return self.model_dump_json(exclude={"coverage": {"lag_seconds"}})


@runtime_checkable
class DeltaSource(Protocol):
    async def poll(self, customer_id: str, domain_id: str, now: datetime) -> DeltaPayload:
        """Current state of one (customer, domain). Both come from the session's derived scope
        and the gateway-authorized subscription; the source never widens them."""
        raise NotImplementedError


class AggregateDeltaSource:
    """Polls ``AggregateReader``; a short TTL cache lets sessions share one read."""

    def __init__(
        self,
        reader: AggregateReader,
        settings: RealtimeSettings,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._reader = reader
        self._settings = settings
        self._clock = clock
        self._ttl = settings.poll_interval_seconds / 2
        self._cache: dict[tuple[str, str], tuple[float, DeltaPayload]] = {}

    async def poll(self, customer_id: str, domain_id: str, now: datetime) -> DeltaPayload:
        key = (customer_id, domain_id)
        started = self._clock()
        cached = self._cache.get(key)
        if cached is not None and 0 <= started - cached[0] < self._ttl:
            return cached[1]
        end = bucket_start(now, "hour") + timedelta(hours=1)
        window = AggregateWindow(start=end - timedelta(hours=2), end=end)
        latency = await self._reader.query(
            customer_id, domain_id, "latency", "hour", window, max_series=1, max_points=2
        )
        errors = await self._reader.query(
            customer_id, domain_id, "errors", "hour", window, max_series=1, max_points=2
        )
        status = await self._reader.status(customer_id)
        payload = self._build(domain_id, latency, errors, status, now)
        self._cache.pop(key, None)
        self._cache[key] = (started, payload)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            del self._cache[next(iter(self._cache))]
        return payload

    def _build(
        self,
        domain_id: str,
        latency: QueryResult,
        errors: QueryResult,
        status: AggregateStatus | None,
        now: datetime,
    ) -> DeltaPayload:
        latest_latency = _latest(latency, LatencyPoint)
        latest_errors = _latest(errors, ErrorPoint)
        error_rate = latest_errors.error_rate if latest_errors is not None else None
        frequency = (
            latest_errors.request_count + latest_errors.unknown_count
            if latest_errors is not None
            else None
        )
        node = DeltaNode(
            id=domain_id,
            kind="cluster",
            label=domain_id.rsplit(":", 1)[-1],
            metrics=NodeMetrics(
                frequency=frequency,
                latency_p95_ms=latest_latency.p95_ms if latest_latency is not None else None,
                health=self._health(error_rate),
            ),
        )
        docs = [d for r in (latency, errors) for s in r.series for d in s.points]
        lag = status.lag_seconds(now) if status is not None else None
        state: CoverageState
        if lag is None:
            state = "unknown"
        elif lag > self._settings.delayed_after_seconds:
            state = "delayed"
        elif not docs or latency.truncated or errors.truncated or not all(d.complete for d in docs):
            state = "partial"
        else:
            state = "complete"
        coverage = Coverage(
            state=state,
            lag_seconds=lag,
            as_of=status.watermark if status is not None else None,
        )
        return DeltaPayload(nodes=(node,), coverage=coverage)

    def _health(self, error_rate: float | None) -> Health:
        if error_rate is None:
            return "unknown"
        if error_rate >= self._settings.health_failing_error_rate:
            return "failing"
        if error_rate >= self._settings.health_degraded_error_rate:
            return "degraded"
        return "ok"


def _latest[P: (LatencyPoint, ErrorPoint)](result: QueryResult, kind: type[P]) -> P | None:
    for series in result.series:
        for point in reversed(series.points):
            if isinstance(point, kind):
                return point
    return None
