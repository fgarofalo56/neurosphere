"""Pure trace assembly: spans, gaps, sampling and late labels (PRP-18 item 5). No I/O.

Documented rules
----------------
* Domain scope: only spans whose ``domain_id`` equals the addressed domain are kept. Spans of any
  other domain (or with no domain) are withheld and reported as ONE ``unknown`` gap with a count;
  a kept span whose parent was withheld is a ``missing_parent`` gap.
* Timing: ``event_time`` is the span start; ``ended_at = started_at + duration_ms`` only when a
  duration was measured (never 0 by default).
* Gap: a span whose ``parent_span_id`` is not among the kept spans. Reason precedence:
  ``late_arrival`` (the orphan itself is late) > ``sampled_out`` (the orphan carries
  ``sampling.rate < 1`` with a head/tail/probabilistic/rate_limited method, so the parent was
  plausibly dropped by sampling) > ``missing_parent``. A parent cycle is an ``unknown`` gap.
* Late span: (a) the archive flagged it late at ingest, or (b) it starts before its parent
  starts, or (c) it was ingested more than ``LATE_GRACE`` after the trace was considered
  complete (the latest end among root spans).
* Sampling: trace rate is the lowest known span rate; ``None`` when no span reports one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from neurosphere_api.replay.models import (
    Completeness,
    Gap,
    GapReason,
    PayloadState,
    Sampling,
    Span,
    SpanKind,
    SpanStatus,
    ToolInfo,
    ToolOutcome,
    TraceDetail,
)
from neurosphere_api.replay.reader import SpanRecord, TraceRecords

__all__ = ["LATE_GRACE", "MAX_SPANS", "assemble_trace"]

LATE_GRACE: Final = timedelta(minutes=5)
MAX_SPANS: Final = 2_000

_KIND: Final[dict[str, SpanKind]] = {
    "request": "agent",
    "agent_run": "agent",
    "delegation": "agent",
    "model_call": "model",
    "tool_call": "tool",
    "retrieval": "retrieval",
}
_SAMPLED_METHODS: Final = frozenset({"head", "tail", "probabilistic", "rate_limited"})
_PAYLOAD_STATES: Final = frozenset(
    {"redacted", "pending", "redaction_failed", "not_required", "unknown"}
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _end(record: SpanRecord) -> datetime | None:
    if record.duration_ms is None:
        return None
    return record.event_time + timedelta(milliseconds=record.duration_ms)


def _status(record: SpanRecord) -> SpanStatus:
    if record.outcome in {"error", "timeout"} or record.span_kind == "error":
        return "error"
    return "ok" if record.outcome == "success" else "unknown"


def _payload_state(record: SpanRecord) -> PayloadState:
    if record.payload_pointer is None:
        return "absent"
    state = record.payload_redaction_state
    return state if state in _PAYLOAD_STATES else "unknown"  # type: ignore[return-value]


def assemble_trace(records: TraceRecords, domain_id: str, trace_id: str) -> TraceDetail | None:
    """Build the trace for ``domain_id``; None when no span of this domain belongs to it."""
    wanted = [r for r in records.spans if r.trace_id == trace_id]
    kept_all = [r for r in wanted if r.domain_id == domain_id]
    withheld = len(wanted) - len(kept_all)
    if not kept_all:
        return None

    unique: dict[str, SpanRecord] = {}
    for rec in sorted(kept_all, key=lambda r: (r.event_time, r.span_id)):
        unique.setdefault(rec.span_id, rec)
    ordered = list(unique.values())
    truncated = records.truncated or len(ordered) > MAX_SPANS
    ordered = ordered[:MAX_SPANS]
    present = {r.span_id for r in ordered}
    withheld_ids = {r.span_id for r in wanted if r.domain_id != domain_id}

    root_ends = [e for r in ordered if r.parent_span_id is None and (e := _end(r)) is not None]
    completed_at = max(root_ends) if root_ends else None

    spans: list[Span] = []
    gaps: list[Gap] = []
    late_count = 0
    for rec in ordered:
        parent = unique.get(rec.parent_span_id) if rec.parent_span_id else None
        late_reason: str | None = None
        if rec.late_flag:
            late_reason = "flagged late at ingest"
        elif parent is not None and rec.event_time < parent.event_time:
            late_reason = "started before its parent"
        elif (
            completed_at is not None
            and rec.ingestion_time is not None
            and rec.ingestion_time > completed_at + LATE_GRACE
        ):
            late_reason = "arrived after the trace was considered complete"
        late_count += late_reason is not None

        rate = rec.sampling_rate
        if rec.parent_span_id is not None and rec.parent_span_id not in present:
            reason: GapReason = "missing_parent"
            detail = "parent span is not in this trace"
            if rec.parent_span_id in withheld_ids:
                detail = "parent span is outside this domain and was withheld"
            elif late_reason is not None:
                reason, detail = "late_arrival", "parent may not have arrived yet"
            elif rate is not None and rate < 1 and rec.sampling_method in _SAMPLED_METHODS:
                reason, detail = "sampled_out", "parent was plausibly dropped by sampling"
            gaps.append(
                Gap(
                    parent_span_id=rec.parent_span_id,
                    reason=reason,
                    span_id=rec.span_id,
                    detail=detail,
                )
            )
        elif _in_cycle(rec, unique):
            gaps.append(
                Gap(
                    parent_span_id=rec.parent_span_id,
                    reason="unknown",
                    span_id=rec.span_id,
                    detail="parent links form a cycle",
                )
            )

        end = _end(rec)
        kind = _KIND.get(rec.span_kind, "other")
        status = _status(rec)
        spans.append(
            Span(
                span_id=rec.span_id,
                parent_span_id=rec.parent_span_id,
                name=rec.model or rec.provider or rec.agent or rec.span_kind,
                kind=kind,
                started_at=_iso(rec.event_time),
                ended_at=None if end is None else _iso(end),
                duration_ms=rec.duration_ms,
                status=status,
                error=rec.outcome if status == "error" else None,
                tool=(
                    ToolInfo(name=rec.provider, outcome=_outcome(rec.outcome))
                    if kind == "tool"
                    else None
                ),
                agent=rec.agent,
                late=late_reason is not None,
                late_reason=late_reason,
                sampled=rate is not None and rate < 1,
                sampling_rate=rate,
                payload_state=_payload_state(rec),
            )
        )

    if withheld:
        gaps.append(
            Gap(
                reason="unknown",
                count=withheld,
                detail=f"{withheld} span(s) belong to another domain and were withheld",
            )
        )

    rated = [r for r in ordered if r.sampling_rate is not None]
    lowest = min(rated, key=lambda r: r.sampling_rate or 0.0) if rated else None
    reason_text = next((r.sampling_reason for r in ([lowest] if lowest else []) if r), None)
    sampling = Sampling(rate=None if lowest is None else lowest.sampling_rate, reason=reason_text)
    partial = bool(gaps) or truncated or (sampling.rate is not None and sampling.rate < 1)
    return TraceDetail(
        trace_id=trace_id,
        spans=tuple(spans),
        gaps=tuple(gaps),
        sampling=sampling,
        completeness=Completeness(
            state="partial" if partial else "complete",
            span_count=len(spans),
            gap_count=len(gaps),
            late_count=late_count,
            withheld_span_count=withheld,
            truncated=truncated,
        ),
    )


def _outcome(value: str) -> ToolOutcome:
    if value == "success":
        return "success"
    if value == "error":
        return "error"
    if value == "cancelled":
        return "cancelled"
    return "timeout" if value == "timeout" else "unknown"


def _in_cycle(rec: SpanRecord, by_id: dict[str, SpanRecord]) -> bool:
    seen = {rec.span_id}
    cursor = rec.parent_span_id
    while cursor is not None and cursor in by_id:
        if cursor in seen:
            return True
        seen.add(cursor)
        cursor = by_id[cursor].parent_span_id
    return False
