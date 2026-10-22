"""Federator: merges authorized per-cell summaries inside ONE cloud and boundary (PRP-21 item 3).

Boundary rules, enforced here and nowhere bypassable:

* A cell is eligible only when its cloud AND boundary id equal the serving deployment's. Naming an
  ineligible cell is refused with ``CapabilityUnavailableError``; by default ineligible cells are
  simply not contacted. There is no code path that sends a credential to, or merges a summary
  from, a cell of another cloud.
* A cell's answer is re-checked on arrival: wrong cell id, cloud, boundary or customer is
  ``capability_unavailable`` (the response is discarded), and any domain the CALLER's scope may not
  read is dropped, so a misbehaving cell cannot widen the caller's view.

Failures never look like zeros: a cell that fails marks the merge incomplete; if no cell answered
and one failed, the request fails with 503.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    UnauthorizedError,
)
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.federation import (
    CellRef,
    CellRegistry,
    CellSummary,
    CloudLiteral,
    DomainSummary,
    combine_cost_totals,
    combine_domain_summaries,
)

from neurosphere_api.federation.cache import SummaryCache, summary_cache_key
from neurosphere_api.federation.client import CellClient
from neurosphere_api.federation.models import CellOutcome, MergedSummary

__all__ = ["FederationState", "Federator"]

_LOG = get_logger("neurosphere_api.federation")


def _eligibility(cell: CellRef, cloud: str, boundary_id: str) -> str | None:
    if cell.cloud != cloud:
        return "cross_cloud_cell"
    if cell.boundary_id != boundary_id:
        return "cross_boundary_cell"
    return None


class Federator:
    def __init__(
        self,
        *,
        serving_cloud: CloudLiteral,
        boundary_id: str,
        registry: CellRegistry,
        clients: Mapping[str, CellClient],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.serving_cloud: CloudLiteral = serving_cloud
        self.boundary_id = boundary_id
        self._registry = registry
        self._clients = dict(clients)
        self._clock = clock or (lambda: datetime.now(UTC))

    def select(self, requested: Sequence[str] | None) -> list[CellRef]:
        """The cells to contact. Naming a cell outside the cloud/boundary is refused."""
        if requested:
            chosen: list[CellRef] = []
            for cell_id in dict.fromkeys(requested):
                cell = self._registry.get(cell_id)
                if cell is None:
                    raise InvalidSchemaError("unknown cell", reason="unknown_cell")
                reason = _eligibility(cell, self.serving_cloud, self.boundary_id)
                if reason is not None:
                    raise CapabilityUnavailableError(
                        reason, "the cell is outside this deployment's cloud boundary"
                    )
                chosen.append(cell)
            return chosen
        eligible = [
            c
            for c in self._registry.cells
            if _eligibility(c, self.serving_cloud, self.boundary_id) is None
        ]
        if not eligible:
            raise CapabilityUnavailableError("no_eligible_cells", "no cell is registered here")
        return eligible

    async def summarize(
        self,
        scope: IdentityScope,
        authorization: str | None,
        *,
        days: int,
        cells: list[CellRef],
    ) -> MergedSummary:
        if scope.cloud != self.serving_cloud:
            raise CapabilityUnavailableError(
                "cross_cloud_scope", "the scope belongs to another cloud"
            )
        for cell in cells:  # defence in depth: select() already guarantees this
            reason = _eligibility(cell, self.serving_cloud, self.boundary_id)
            if reason is not None:
                raise CapabilityUnavailableError(reason, "the cell is outside the boundary")
        results = await asyncio.gather(
            *(self._one(cell, scope, authorization, days) for cell in cells),
            return_exceptions=True,
        )
        outcomes: list[CellOutcome] = []
        summaries: list[CellSummary] = []
        for cell, result in zip(cells, results, strict=True):
            if isinstance(result, CellSummary):
                outcomes.append(CellOutcome(cell_id=cell.cell_id, state="ok"))
                summaries.append(result)
            elif isinstance(result, (ForbiddenError, UnauthorizedError)):
                outcomes.append(CellOutcome(cell_id=cell.cell_id, state="denied"))
            elif isinstance(result, CapabilityUnavailableError):
                raise result
            elif isinstance(result, Exception):
                _LOG.warning("federation cell failed", extra={"cell_id": cell.cell_id})
                outcomes.append(CellOutcome(cell_id=cell.cell_id, state="unavailable"))
            else:
                raise result
        states = {o.state for o in outcomes}
        if "ok" not in states and "unavailable" in states:
            raise DependencyTransientError("no cell answered", reason="cells_unavailable")
        return self._merge(scope, outcomes, summaries, days)

    async def _one(
        self, cell: CellRef, scope: IdentityScope, authorization: str | None, days: int
    ) -> CellSummary:
        client = self._clients.get(cell.cell_id)
        if client is None:
            raise DependencyTransientError("no client for cell", reason="cell_unconfigured")
        summary = await client.fetch_summary(cell, authorization, days)
        if (
            summary.cell_id != cell.cell_id
            or summary.cloud != self.serving_cloud
            or summary.boundary_id != self.boundary_id
            or summary.customer_id != scope.customer_id
        ):
            raise CapabilityUnavailableError(
                "cell_response_mismatch", "a cell answered for a different cloud or boundary"
            )
        return summary

    def _merge(
        self,
        scope: IdentityScope,
        outcomes: list[CellOutcome],
        summaries: list[CellSummary],
        days: int,
    ) -> MergedSummary:
        allowed = domains_with_permission(scope, Permission.DATA_READ, now=self._clock())
        by_domain: dict[str, list[DomainSummary]] = {}
        for summary in summaries:
            for row in summary.domains:
                if row.domain_id not in allowed:
                    _LOG.warning("federation dropped an out-of-scope domain row")
                    continue
                by_domain.setdefault(row.domain_id, []).append(row)
        domains = tuple(combine_domain_summaries(d, rows) for d, rows in sorted(by_domain.items()))
        all_costs = [c for d in domains for c in d.costs]
        first = summaries[0] if summaries else None
        now = self._clock()
        return MergedSummary(
            cloud=self.serving_cloud,
            boundary_id=self.boundary_id,
            customer_id=scope.customer_id,
            window_start=first.window_start if first else now,
            window_end=first.window_end if first else now,
            cells=tuple(outcomes),
            domains=domains,
            totals=combine_cost_totals(all_costs),
            complete=bool(domains)
            and all(o.state == "ok" for o in outcomes)
            and all(d.complete for d in domains)
            and not any(s.truncated for s in summaries),
            truncated=any(s.truncated for s in summaries),
        )


@dataclass(frozen=True, slots=True)
class FederationState:
    """What ``app.state.federation`` holds. Built by the deployment, never from a request."""

    federator: Federator
    cache: SummaryCache
    local_cell: CellRef | None = None

    def cache_key(self, scope: IdentityScope, *, days: int, cells: list[CellRef]) -> str:
        return summary_cache_key(scope, days=days, cell_ids=[c.cell_id for c in cells])
