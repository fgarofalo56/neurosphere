"""Wire models for the replay API (PRP-18 item 5). Read-only: nothing here describes a command.

Shapes follow the PRP-18 wire contract. Additive fields beyond the contract: ``Gap.span_id`` /
``Gap.detail`` / ``Gap.count``, ``Completeness`` detail counts, ``Span.agent``, ``TraceSummary``.
``None`` means not reported; nothing defaults to 0 (a measured zero is ``0``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Completeness",
    "Gap",
    "GapReason",
    "PayloadState",
    "Sampling",
    "Span",
    "SpanKind",
    "SpanStatus",
    "ToolInfo",
    "ToolOutcome",
    "TraceDetail",
    "TracePage",
    "TraceSummary",
]

ToolOutcome = Literal["success", "error", "cancelled", "timeout", "unknown"]
SpanKind = Literal["agent", "model", "tool", "retrieval", "other"]
SpanStatus = Literal["ok", "error", "unknown"]
GapReason = Literal["missing_parent", "sampled_out", "late_arrival", "unknown"]
PayloadState = Literal[
    "absent", "redacted", "pending", "redaction_failed", "not_required", "unknown"
]


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolInfo(_Wire):
    name: str | None = None  # the telemetry contract carries no tool name; None = not reported
    outcome: ToolOutcome = "unknown"


class Sampling(_Wire):
    rate: float | None = None  # lowest known rate in the trace; None = not reported
    reason: str | None = None


class Span(_Wire):
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: SpanKind
    started_at: str
    ended_at: str | None = None  # None when no duration was measured
    duration_ms: int | None = None
    status: SpanStatus
    error: str | None = None  # a code (the outcome), never a message body
    tool: ToolInfo | None = None
    agent: str | None = None
    late: bool = False
    late_reason: str | None = None
    sampled: bool = False  # this span's own sampling rate is below 1
    sampling_rate: float | None = None
    payload_state: PayloadState = "absent"
    payload: dict[str, Any] | None = None  # only with policy AND explicit opt-in


class Gap(_Wire):
    parent_span_id: str | None = None
    reason: GapReason
    span_id: str | None = None  # the orphaned span, when the gap hangs off one
    count: int = Field(default=1, ge=1)
    detail: str


class Completeness(_Wire):
    state: Literal["complete", "partial", "unknown"]
    span_count: int
    gap_count: int
    late_count: int
    withheld_span_count: int  # spans of another domain dropped from this view
    truncated: bool = False


class TraceDetail(_Wire):
    trace_id: str
    spans: tuple[Span, ...]
    gaps: tuple[Gap, ...]
    sampling: Sampling
    completeness: Completeness


class TraceSummary(_Wire):
    trace_id: str
    started_at: str
    span_count: int
    error_count: int
    sampling_rate: float | None = None
    root_name: str | None = None


class TracePage(_Wire):
    items: tuple[TraceSummary, ...]
    next_cursor: str | None = None
