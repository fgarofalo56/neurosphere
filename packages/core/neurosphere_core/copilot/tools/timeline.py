"""``get_timeline``: what changed in the caller's domains over a bounded recent window.

Three sections, each read through a narrow port and each scoped by the server-derived
``IdentityScope`` (never by an argument):

* ``changes``: audited changes, only in domains where the caller holds ``audit.read``. A caller
  with ``data.read`` but without ``audit.read`` still gets the other sections; the missing one is
  reported in ``sections_omitted`` (partial, not denied).
* ``metric_shifts``: per ``data.read`` domain, hour-grain ``errors`` and ``latency`` aggregates of
  the window compared with the previous window of equal length (rule on ``_errors_value`` and
  ``_latency_value``).
* ``recommendations``: recommendations created inside the window.

Entries are merged newest first and capped at ``MAX_TIMELINE_ENTRIES``. Entries never carry an
actor (name, id or pseudonym) and never a before/after body.

The result also carries one ``timeline_meta`` record (coverage: ``sections_included`` and
``sections_omitted`` with reason codes) so the answer can say what is missing. It has NO citation:
a citation must point at a real source record and the meta record is not one, so it can never be
cited (``unknown_citations`` would flag any attempt).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal

from neurosphere_contracts.query.v1.budget import Budget
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, field_validator

from neurosphere_core.aggregates import AggregateWindow, ErrorPoint, LatencyPoint, parse_time
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.copilot.tools.args import ToolArgs
from neurosphere_core.copilot.tools.errors import ToolPermissionError
from neurosphere_core.copilot.tools.models import Citation, FreshnessPolicy, ToolRecord, ToolResult
from neurosphere_core.copilot.tools.ports import (
    ChangeLogReader,
    MetricsReader,
    RecommendationReader,
)
from neurosphere_core.copilot.tools.registry import ToolSpec
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_TIMELINE_ENTRIES",
    "MAX_TIMELINE_WINDOW",
    "TOOL_NAME",
    "TimelineArgs",
    "TimelineEntry",
    "get_timeline_spec",
]

TOOL_NAME: Final = "get_timeline"
MAX_TIMELINE_WINDOW: Final = timedelta(hours=24)
MAX_TIMELINE_ENTRIES: Final = 100
META_RECORD_ID: Final = "timeline_meta"

Section = Literal["changes", "metric_shifts", "recommendations"]
_ALL_SECTIONS: Final[tuple[Section, ...]] = ("changes", "metric_shifts", "recommendations")
_METRIC_POINTS: Final = 50


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TimelineArgs(ToolArgs):
    """Window and sections only. No scope, domain or free-text field exists."""

    window_minutes: Annotated[StrictInt, Field(ge=5, le=1440)]
    sections: list[Section] | None = None
    budget: Budget | None = None

    @field_validator("sections")
    @classmethod
    def _no_duplicates(cls, value: list[Section] | None) -> list[Section] | None:
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("sections must be non-empty and without duplicates")
        return value

    def requested_budget(self) -> Budget | None:
        return self.budget


class TimelineEntry(BaseModel):
    """One timeline line. Kind-specific fields are bounded scalars; nothing free-form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["change", "metric_shift", "recommendation"]
    occurred_at: str
    domain_id: str
    subject_id: str
    operation: str | None = None
    outcome: str | None = None
    metric: Literal["errors", "latency"] | None = None
    previous: float | None = None
    current: float | None = None
    delta: float | None = None
    recommendation_id: str | None = None
    recommendation_kind: str | None = None


# (record_id, source, as_of, sort key, entry)
_Item = tuple[str, str, str | None, datetime, TimelineEntry]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _errors_value(points: Sequence[object]) -> float | None:
    """Total known ``error_count`` of the window; ``None`` when no point knows its count."""
    counts = [
        p.error_count for p in points if isinstance(p, ErrorPoint) and p.error_count is not None
    ]
    return float(sum(counts)) if counts else None


def _latency_value(points: Sequence[object]) -> float | None:
    """Mean of the hourly ``p95_ms`` of the window (1 decimal); ``None`` when none is known."""
    values = [p.p95_ms for p in points if isinstance(p, LatencyPoint) and p.p95_ms is not None]
    return round(sum(values) / len(values), 1) if values else None


_SHIFT_METRICS: Final[
    tuple[tuple[Literal["errors", "latency"], Callable[[Sequence[object]], float | None]], ...]
] = (
    ("errors", _errors_value),
    ("latency", _latency_value),
)


def _in_window(moment: datetime, start: datetime, end: datetime) -> bool:
    return start <= moment <= end


def get_timeline_spec(
    *,
    changes: ChangeLogReader | None,
    metrics: MetricsReader,
    recommendations: RecommendationReader,
    clock: Callable[[], datetime] = _utc_now,
    freshness: FreshnessPolicy = FreshnessPolicy(),  # noqa: B008 - frozen, shared by design
) -> ToolSpec:
    async def run(scope: IdentityScope, args: TimelineArgs) -> ToolResult:
        now = clock()
        readable = tuple(sorted(domains_with_permission(scope, Permission.DATA_READ, now=now)))
        if not readable:
            raise ToolPermissionError(Permission.DATA_READ.value)
        audited = tuple(sorted(domains_with_permission(scope, Permission.AUDIT_READ, now=now)))
        wanted = set(args.sections) if args.sections is not None else set(_ALL_SECTIONS)
        start = now - timedelta(minutes=args.window_minutes)
        items: list[_Item] = []
        omitted_pairs: list[tuple[str, str]] = []
        truncated = False

        if "changes" in wanted:
            if changes is None:
                omitted_pairs.append(("changes", "change_log_unavailable"))
            elif not audited:
                omitted_pairs.append(("changes", "audit_read_not_held"))
            else:
                records = await changes.changes(
                    scope, audited, start, now, limit=MAX_TIMELINE_ENTRIES + 1
                )
                for rec in records:
                    if rec.domain_id not in audited or not _in_window(rec.occurred_at, start, now):
                        continue
                    entry = TimelineEntry(
                        kind="change",
                        occurred_at=_iso(rec.occurred_at),
                        domain_id=rec.domain_id,
                        subject_id=rec.subject_id,
                        operation=rec.operation,
                        outcome=rec.outcome,
                    )
                    items.append(
                        (rec.record_id, "audit", entry.occurred_at, rec.occurred_at, entry)
                    )

        if "metric_shifts" in wanted:
            shifts = await _metric_shifts(metrics, scope, readable, start, now)
            items.extend(shifts)

        if "recommendations" in wanted:
            for domain in readable:
                page = await recommendations.list(scope, domain, limit=MAX_TIMELINE_ENTRIES + 1)
                truncated = truncated or page.next_cursor is not None
                for rec in page.items:
                    created = _parse_iso(rec.created_at.root)
                    if (
                        rec.domain_id.root != domain
                        or created is None
                        or not _in_window(created, start, now)
                    ):
                        continue
                    entry = TimelineEntry(
                        kind="recommendation",
                        occurred_at=_iso(created),
                        domain_id=domain,
                        subject_id=rec.subject_ids[0].root,
                        recommendation_id=rec.recommendation_id.root,
                        recommendation_kind=rec.kind,
                    )
                    items.append(
                        (
                            rec.recommendation_id.root,
                            "recommendations",
                            rec.created_at.root,
                            created,
                            entry,
                        )
                    )

        # Newest first; the record id breaks ties so the order is deterministic.
        items.sort(key=lambda item: (item[3], item[0]), reverse=True)
        if len(items) > MAX_TIMELINE_ENTRIES:
            items, truncated = items[:MAX_TIMELINE_ENTRIES], True

        records_out: list[ToolRecord] = []
        citations: list[Citation] = []
        for record_id, source, as_of, _, entry in items:
            records_out.append(
                ToolRecord(
                    record_id=record_id,
                    kind=entry.kind,
                    data=entry.model_dump(mode="json", exclude_none=True),
                )
            )
            citations.append(
                Citation(
                    record_id=record_id,
                    kind=entry.kind,
                    source=source,
                    as_of=as_of,
                    freshness=freshness.state(as_of, now),
                )
            )
        omitted_names = {name for name, _ in omitted_pairs}
        included: list[JsonValue] = [
            s for s in _ALL_SECTIONS if s in wanted and s not in omitted_names
        ]
        omitted: list[JsonValue] = [{"section": n, "reason": r} for n, r in omitted_pairs]
        records_out.append(
            ToolRecord(
                record_id=META_RECORD_ID,
                kind="timeline_meta",
                data={
                    "window_start": _iso(start),
                    "window_end": _iso(now),
                    "sections_included": included,
                    "sections_omitted": omitted,
                },
            )
        )
        return ToolResult(
            tool=TOOL_NAME,
            records=tuple(records_out),
            citations=tuple(citations),
            truncated=truncated,
        )

    return ToolSpec(
        TOOL_NAME,
        "Recent changes, metric shifts and new recommendations in the caller's domains.",
        TimelineArgs,
        Permission.DATA_READ,
        run,
    )


async def _metric_shifts(
    metrics: MetricsReader,
    scope: IdentityScope,
    domains: Sequence[str],
    start: datetime,
    now: datetime,
) -> list[_Item]:
    """Shift entries: the window's value differs from the previous equal-length window.

    Both values must be known (an unknown is never treated as 0). ``delta = current - previous``.
    The entry reuses the id of the latest current-window aggregate point, a real record, so its
    citation is genuine.
    """
    span = now - start
    current_window = AggregateWindow(start=start, end=now)
    previous_window = AggregateWindow(start=start - span, end=start)
    out: list[_Item] = []
    for domain in domains:
        for metric, value_of in _SHIFT_METRICS:
            now_result = await metrics.query(
                scope.customer_id,
                domain,
                metric,
                "hour",
                current_window,
                max_series=5,
                max_points=_METRIC_POINTS,
            )
            before_result = await metrics.query(
                scope.customer_id,
                domain,
                metric,
                "hour",
                previous_window,
                max_series=5,
                max_points=_METRIC_POINTS,
            )
            current_points = [
                p for s in now_result.series for p in s.points if p.domain_id == domain
            ]
            previous_points = [
                p for s in before_result.series for p in s.points if p.domain_id == domain
            ]
            current = value_of(current_points)
            previous = value_of(previous_points)
            if current is None or previous is None or current == previous or not current_points:
                continue
            latest = max(current_points, key=lambda p: (p.bucket_start, p.id))
            occurred = parse_time(latest.bucket_start)
            entry = TimelineEntry(
                kind="metric_shift",
                occurred_at=_iso(occurred),
                domain_id=domain,
                subject_id=domain,
                metric=metric,
                previous=previous,
                current=current,
                delta=round(current - previous, 1),
            )
            out.append((latest.id, "aggregates", latest.watermark, occurred, entry))
    return out
