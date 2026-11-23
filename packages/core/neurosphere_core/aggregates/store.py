"""Aggregate store protocols and the in-memory implementation.

``AggregateReader`` is the ONLY surface the API (dashboards, reconciliation) uses: bounded reads of
materialized documents. It never touches the ledger or the analytics adapter, so the views keep
working when either is down. ``AggregateStore`` adds the write side the projection worker needs.

Every read takes caller-supplied ``max_series`` and ``max_points`` and reports ``truncated``; the
hour grain is limited to ``HOUR_RETENTION_DAYS`` of window.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from neurosphere_core.aggregates.models import (
    HOUR_RETENTION_DAYS,
    AggregateDoc,
    AggregateSeries,
    AggregateStatus,
    AggregateWindow,
    Contribution,
    Grain,
    Metric,
    QueryResult,
    format_bucket,
)
from neurosphere_core.aggregates.subject import (
    MAX_SUBJECT_KEYS_PER_READ,
    SubjectKind,
    SubjectLookup,
    SubjectPoint,
)
from neurosphere_core.errors import InvalidSchemaError

MAX_SERIES_CEILING = 50
MAX_POINTS_CEILING = 2160


def validate_query(grain: Grain, window: AggregateWindow, max_series: int, max_points: int) -> None:
    """Shared bounds check; raises ``InvalidSchemaError`` (HTTP 422) for an unbounded request."""
    if not 1 <= max_series <= MAX_SERIES_CEILING:
        raise InvalidSchemaError(f"max_series must be 1..{MAX_SERIES_CEILING}")
    if not 1 <= max_points <= MAX_POINTS_CEILING:
        raise InvalidSchemaError(f"max_points must be 1..{MAX_POINTS_CEILING}")
    if grain == "hour" and window.span.total_seconds() > HOUR_RETENTION_DAYS * 86_400:
        raise InvalidSchemaError(
            f"the hour grain is limited to {HOUR_RETENTION_DAYS} days", reason="hour_window"
        )


def select_series(docs: Sequence[AggregateDoc], max_series: int, max_points: int) -> QueryResult:
    """Group by series key (sorted), keep the first ``max_series`` series and, per series, the
    NEWEST ``max_points`` points (returned oldest first)."""
    by_key: dict[str, list[AggregateDoc]] = {}
    for doc in docs:
        by_key.setdefault(doc.series_key, []).append(doc)
    keys = sorted(by_key)
    truncated = len(keys) > max_series
    series: list[AggregateSeries] = []
    for key in keys[:max_series]:
        points = sorted(by_key[key], key=lambda d: d.bucket_start)
        if len(points) > max_points:
            truncated = True
            points = points[-max_points:]
        series.append(AggregateSeries(key=key, points=tuple(points)))
    return QueryResult(series=tuple(series), truncated=truncated)


def validate_subject_window(window: AggregateWindow) -> None:
    """Subject reads are hour grain: same retention bound as ``validate_query``."""
    if window.span.total_seconds() > HOUR_RETENTION_DAYS * 86_400:
        raise InvalidSchemaError(
            f"the hour grain is limited to {HOUR_RETENTION_DAYS} days", reason="hour_window"
        )


def bounded_keys(keys: Sequence[str]) -> tuple[list[str], bool]:
    """Distinct keys, sorted, at most ``MAX_SUBJECT_KEYS_PER_READ``; flag when some were dropped."""
    ordered = sorted(set(keys))
    return ordered[:MAX_SUBJECT_KEYS_PER_READ], len(ordered) > MAX_SUBJECT_KEYS_PER_READ


def pick_latest(
    docs: Sequence[AggregateDoc], keys: Sequence[str], truncated: bool
) -> SubjectLookup:
    """Newest subject point per requested key (``bucket_start`` decides, then id for ties)."""
    wanted = set(keys)
    best: dict[str, SubjectPoint] = {}
    for doc in docs:
        if not isinstance(doc, SubjectPoint) or doc.series_key not in wanted:
            continue
        current = best.get(doc.series_key)
        if current is None or (doc.bucket_start, doc.id) > (current.bucket_start, current.id):
            best[doc.series_key] = doc
    return SubjectLookup(points=best, truncated=truncated)


def pick_newest(docs: Sequence[AggregateDoc], limit: int) -> SubjectLookup:
    """The ``limit`` subjects whose newest point is newest (ties broken by series key)."""
    # Realtime guard (PRP-100): only agent and model subjects; tool/service never reach the delta.
    docs = [d for d in docs if isinstance(d, SubjectPoint) and d.subject_kind in ("agent", "model")]
    best = pick_latest(docs, [d.series_key for d in docs], False).points
    ranked = sorted(best.values(), key=lambda p: p.series_key)
    ranked.sort(key=lambda p: p.bucket_start, reverse=True)  # stable: ties stay ordered by key
    kept = ranked[: max(0, limit)]
    return SubjectLookup(points={p.series_key: p for p in kept}, truncated=len(ranked) > len(kept))


@runtime_checkable
class AggregateReader(Protocol):
    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        """Documents of one customer/domain/metric/grain with ``bucket_start`` in the window.

        Scoped to exactly one customer and one domain: callers pass the domain their derived
        scope allows, never a caller-supplied value. Raises ``InvalidSchemaError`` when the
        bounds are out of range or the hour window is too wide.
        """
        raise NotImplementedError

    async def status(self, customer_id: str) -> AggregateStatus | None:
        """Watermark and billing freshness for the customer; ``None`` before anything applied."""
        raise NotImplementedError


@runtime_checkable
class AggregateStore(AggregateReader, Protocol):
    async def get_contribution(self, customer_id: str, contribution_id: str) -> Contribution | None:
        raise NotImplementedError

    async def put_contribution(self, contribution: Contribution) -> None:
        """Upsert by id (a changed subject replaces its previous contribution)."""
        raise NotImplementedError

    async def delete_contribution(self, customer_id: str, contribution_id: str) -> None:
        """Idempotent: deleting an absent contribution is a no-op."""
        raise NotImplementedError

    async def list_contributions(
        self, customer_id: str, domain_id: str, day: date
    ) -> list[Contribution]:
        """Contributions of one domain whose ``occurred_at`` falls on the UTC ``day``."""
        raise NotImplementedError

    async def replace_bucket(
        self,
        customer_id: str,
        domain_id: str,
        grain: Grain,
        start: str,
        docs: Sequence[AggregateDoc],
    ) -> None:
        """Make ``docs`` the complete content of one bucket: upsert them, delete any other
        document of that bucket. Idempotent."""
        raise NotImplementedError

    async def put_status(self, status: AggregateStatus) -> None:
        raise NotImplementedError

    async def prune(self, customer_id: str, *, day_cutoff: date, hour_cutoff: datetime) -> int:
        """Delete contributions before ``day_cutoff`` and documents of buckets older than the
        grain's cutoff (day docs before ``day_cutoff``, hour docs before ``hour_cutoff``).
        Returns the number of deleted documents."""
        raise NotImplementedError


class InMemoryAggregateStore:
    def __init__(self) -> None:
        self._contributions: dict[tuple[str, str], Contribution] = {}
        self._docs: dict[tuple[str, str], AggregateDoc] = {}
        self._status: dict[str, AggregateStatus] = {}
        self.document_writes = 0
        """Aggregate documents actually written by ``replace_bucket`` (test counter)."""

    # ---- read side

    def _subject_docs(
        self, customer_id: str, domain_id: str, window: AggregateWindow
    ) -> list[AggregateDoc]:
        start, end = format_bucket(window.start), format_bucket(window.end)
        return [
            doc
            for (cust, _), doc in self._docs.items()
            if cust == customer_id
            and doc.domain_id == domain_id
            and doc.metric == "subject"
            and doc.grain == "hour"
            and start <= doc.bucket_start < end
        ]

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        validate_subject_window(window)
        kept, truncated = bounded_keys(keys)
        docs = [
            d
            for d in self._subject_docs(customer_id, domain_id, window)
            if isinstance(d, SubjectPoint) and d.subject_kind == kind
        ]
        return pick_latest(docs, kept, truncated)

    async def newest_subject_points(
        self, customer_id: str, domain_id: str, window: AggregateWindow, limit: int
    ) -> SubjectLookup:
        validate_subject_window(window)
        return pick_newest(self._subject_docs(customer_id, domain_id, window), limit)

    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        validate_query(grain, window, max_series, max_points)
        start, end = format_bucket(window.start), format_bucket(window.end)
        found = [
            doc
            for (cust, _), doc in self._docs.items()
            if cust == customer_id
            and doc.domain_id == domain_id
            and doc.metric == metric
            and doc.grain == grain
            and start <= doc.bucket_start < end
        ]
        return select_series(found, max_series, max_points)

    async def status(self, customer_id: str) -> AggregateStatus | None:
        return self._status.get(customer_id)

    # ---- write side

    async def get_contribution(self, customer_id: str, contribution_id: str) -> Contribution | None:
        return self._contributions.get((customer_id, contribution_id))

    async def put_contribution(self, contribution: Contribution) -> None:
        self._contributions[(contribution.customer_id, contribution.id)] = contribution

    async def delete_contribution(self, customer_id: str, contribution_id: str) -> None:
        self._contributions.pop((customer_id, contribution_id), None)

    async def list_contributions(
        self, customer_id: str, domain_id: str, day: date
    ) -> list[Contribution]:
        found = [
            c
            for (cust, _), c in self._contributions.items()
            if cust == customer_id and c.domain_id == domain_id and c.occurred.date() == day
        ]
        return sorted(found, key=lambda c: c.id)

    async def replace_bucket(
        self,
        customer_id: str,
        domain_id: str,
        grain: Grain,
        start: str,
        docs: Sequence[AggregateDoc],
    ) -> None:
        keep = {doc.id for doc in docs}
        for key, existing in list(self._docs.items()):
            if (
                key[0] == customer_id
                and existing.domain_id == domain_id
                and existing.grain == grain
                and existing.bucket_start == start
                and key[1] not in keep
            ):
                del self._docs[key]
        for doc in docs:
            if self._docs.get((customer_id, doc.id)) != doc:  # unchanged documents are skipped
                self._docs[(customer_id, doc.id)] = doc
                self.document_writes += 1

    async def put_status(self, status: AggregateStatus) -> None:
        self._status[status.customer_id] = status

    async def prune(self, customer_id: str, *, day_cutoff: date, hour_cutoff: datetime) -> int:
        removed = 0
        for key, contribution in list(self._contributions.items()):
            if key[0] == customer_id and contribution.occurred.date() < day_cutoff:
                del self._contributions[key]
                removed += 1
        day_limit, hour_limit = day_cutoff.isoformat(), format_bucket(hour_cutoff)
        for key, doc in list(self._docs.items()):
            if key[0] != customer_id:
                continue
            stale = (
                doc.bucket_start[:10] < day_limit
                if doc.grain == "day"
                else doc.bucket_start < hour_limit
            )
            if stale:
                del self._docs[key]
                removed += 1
        return removed

    # ---- test helpers

    def documents(self, customer_id: str) -> dict[str, AggregateDoc]:
        return {doc_id: d for (cust, doc_id), d in self._docs.items() if cust == customer_id}

    def contributions(self, customer_id: str) -> dict[str, Contribution]:
        return {cid: c for (cust, cid), c in self._contributions.items() if cust == customer_id}


__all__ = [
    "MAX_POINTS_CEILING",
    "MAX_SERIES_CEILING",
    "AggregateReader",
    "AggregateStore",
    "InMemoryAggregateStore",
    "bounded_keys",
    "pick_latest",
    "pick_newest",
    "select_series",
    "validate_query",
    "validate_subject_window",
]
