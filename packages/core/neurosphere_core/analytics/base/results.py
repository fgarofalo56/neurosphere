"""Decode engine rows into contract results; deterministic ordering shared by all adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from neurosphere_core.analytics.base.models import (
    AggregateResult,
    AggregateRow,
    Cloud,
    ExecutionStats,
)
from neurosphere_core.analytics.base.plan import QueryPlan

_EPOCH = datetime.min.replace(tzinfo=UTC)


def sort_rows(rows: list[AggregateRow]) -> tuple[AggregateRow, ...]:
    """Bucket then keys; unknown (None) sorts first. Never relies on engine collation."""
    return tuple(
        sorted(
            rows,
            key=lambda r: (
                r.bucket or _EPOCH,
                tuple((k is not None, k or "") for k in r.keys),
            ),
        )
    )


def decode_value(raw: object) -> Decimal | None:
    """Engines return int, float, Decimal or str; unknown stays None (never 0)."""
    if raw is None:
        return None
    return raw if isinstance(raw, Decimal) else Decimal(str(raw))


def decode_bucket(raw: object) -> datetime:
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, str):
        value = datetime.fromisoformat(raw)
    else:
        raise TypeError("time bucket must be a datetime or an ISO string")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def decode_rows(plan: QueryPlan, raw_rows: tuple[tuple[object, ...], ...]) -> list[AggregateRow]:
    """Layout: group keys, optional bucket, value, row_count, known_count (see dialect.py)."""
    n = len(plan.group_by)
    has_bucket = plan.time_bucket is not None
    value_at = n + (1 if has_bucket else 0)
    out: list[AggregateRow] = []
    for raw in raw_rows:
        row_count = int(str(raw[value_at + 1]))
        known = int(str(raw[value_at + 2]))
        out.append(
            AggregateRow(
                keys=tuple(None if k is None else str(k) for k in raw[:n]),
                bucket=decode_bucket(raw[n]) if has_bucket else None,
                value=decode_value(raw[value_at]),
                row_count=row_count,
                unknown_count=row_count - known,
            )
        )
    return out


def build_result(
    plan: QueryPlan,
    rows: list[AggregateRow],
    *,
    backend: str,
    cloud: Cloud,
    stats: ExecutionStats,
) -> AggregateResult:
    return AggregateResult(
        backend=backend,
        cloud=cloud,
        metric=plan.metric,
        aggregation=plan.aggregation,
        quantile=float(plan.quantile) if plan.quantile is not None else None,
        group_by=plan.group_by,
        time_bucket=plan.time_bucket,
        rows=sort_rows(rows),
        stats=stats,
    )
