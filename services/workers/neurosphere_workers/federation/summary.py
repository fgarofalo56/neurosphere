"""Per-cell scope-filtered aggregate summary (PRP-21 item 3).

``compute_cell_summary`` runs INSIDE a cell with the ``IdentityScope`` that cell derived from the
caller's credential. It reads only the hot aggregates (``AggregateReader``), one query per domain
the scope may read (``domains_with_permission``) and never a domain outside that set, so a
restricted principal's summary has no identity, count or cost from anywhere else. Nothing but the
rolled-up numbers leaves this function.

Cost totals are kept per (kind, currency): estimated and invoiced are never added, and an unknown
amount is ``None`` (the total is then incomplete), never 0.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from neurosphere_core.aggregates import (
    AggregateReader,
    AggregateWindow,
    CostPoint,
    ErrorPoint,
    bucket_start,
)
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.federation.models import (
    CellRef,
    CellSummary,
    CostTotal,
    DomainSummary,
    combine_cost_totals,
)

__all__ = ["MAX_DAYS", "compute_cell_summary"]

MAX_DAYS: Final = 90
_MAX_SERIES: Final = 50
_MAX_POINTS: Final = MAX_DAYS + 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def compute_cell_summary(
    reader: AggregateReader,
    scope: IdentityScope,
    *,
    cell: CellRef,
    days: int = 30,
    clock: Callable[[], datetime] = _utcnow,
) -> CellSummary:
    """Aggregate summary of the domains ``scope`` may read, in this cell only."""
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be 1..{MAX_DAYS}")
    if cell.cloud != scope.cloud:
        # A cell never answers for a scope of another cloud (no Government/Commercial bridge).
        raise CapabilityUnavailableError(
            "cross_cloud_scope", "this cell does not serve a scope from another cloud"
        )
    now = clock()
    end = bucket_start(now, "day") + timedelta(days=1)
    window = AggregateWindow(start=end - timedelta(days=days), end=end)
    domains: list[DomainSummary] = []
    truncated = False
    for domain_id in sorted(domains_with_permission(scope, Permission.DATA_READ, now=now)):
        summary, cut = await _domain(reader, scope.customer_id, domain_id, window)
        truncated = truncated or cut
        domains.append(summary)
    return CellSummary(
        cell_id=cell.cell_id,
        cloud=cell.cloud,
        boundary_id=cell.boundary_id,
        customer_id=scope.customer_id,
        scope_hash=scope.scope_hash,
        window_start=window.start,
        window_end=window.end,
        domains=tuple(domains),
        truncated=truncated,
    )


async def _domain(
    reader: AggregateReader, customer_id: str, domain_id: str, window: AggregateWindow
) -> tuple[DomainSummary, bool]:
    cost = await reader.query(
        customer_id,
        domain_id,
        "cost",
        "day",
        window,
        max_series=_MAX_SERIES,
        max_points=_MAX_POINTS,
    )
    errors = await reader.query(
        customer_id,
        domain_id,
        "errors",
        "day",
        window,
        max_series=_MAX_SERIES,
        max_points=_MAX_POINTS,
    )
    totals: list[CostTotal] = []
    for series in cost.series:
        totals.extend(
            CostTotal(kind=p.kind, currency=p.currency, amount=p.amount, complete=p.complete)
            for p in series.points
            if isinstance(p, CostPoint)
        )
    requests: list[int] = []
    error_counts: list[int] = []
    unknown: list[int] = []
    for series in errors.series:
        for point in series.points:
            if not isinstance(point, ErrorPoint):
                continue
            requests.append(point.request_count)
            unknown.append(point.unknown_count)
            if point.error_count is not None:
                error_counts.append(point.error_count)
    merged_costs = combine_cost_totals(totals)
    has_errors = bool(requests)
    cut = cost.truncated or errors.truncated
    summary = DomainSummary(
        domain_id=domain_id,
        request_count=sum(requests) if has_errors else None,
        error_count=sum(error_counts) if error_counts else None,
        unknown_outcome_count=sum(unknown) if has_errors else None,
        costs=merged_costs,
        complete=(
            not cut
            and has_errors
            and bool(merged_costs)
            and all(c.complete for c in merged_costs)
            and len(error_counts) == len(requests)
        ),
    )
    return summary, cut
