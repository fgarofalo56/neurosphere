"""Builders for the subject-series store tests (synthetic data only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_core.aggregates import (
    AggregateWindow,
    SubjectPoint,
    aggregate_doc_id,
    format_bucket,
)

CUST = "cust-1"
DOMAIN = "dom-a"
NOW = datetime(2026, 11, 14, 12, 30, tzinfo=UTC)


def hour(offset: int) -> datetime:
    """Hour bucket ``offset`` hours before the current one."""
    return NOW.replace(minute=0) - timedelta(hours=offset)


def window(hours: int = 2) -> AggregateWindow:
    end = NOW.replace(minute=0) + timedelta(hours=1)
    return AggregateWindow(start=end - timedelta(hours=hours), end=end)


def point(
    key: str,
    offset: int = 0,
    *,
    customer: str = CUST,
    domain: str = DOMAIN,
    events: int = 3,
    p95: int | None = 120,
    error_rate: float | None = 0.0,
) -> SubjectPoint:
    start = format_bucket(hour(offset))
    kind: Any = key.split(":", 1)[0]
    return SubjectPoint(
        id=aggregate_doc_id(customer, domain, "subject", "hour", start, key),
        customer_id=customer,
        domain_id=domain,
        grain="hour",
        bucket_start=start,
        series_key=key,
        watermark=start,
        complete=True,
        subject_kind=kind,
        subject_key=key,
        event_count=events,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_count=None if error_rate is None else 0,
        error_rate=error_rate,
        p50_ms=p95,
        p95_ms=p95,
        input_tokens=10,
        output_tokens=20,
        tokens_known_count=events,
    )
