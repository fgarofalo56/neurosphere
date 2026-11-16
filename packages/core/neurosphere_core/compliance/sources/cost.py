"""Cost attribution evidence (PRP-56 item 3).

Counts the domain's ledger entries in the window with and without a cost-center tag. No amount,
model or request id leaves this module. When the ledger entries carry no cost-center attribute at
all (a data shape that predates cost-center attribution) the source reports ``not_collected``.
"""

from __future__ import annotations

from datetime import datetime

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    unavailable,
)
from neurosphere_core.ledger import LedgerStore
from neurosphere_core.ledger.totals import TimeWindow

__all__ = ["CostAttributionSource"]

_MEASURES = ("records", "entries_with_cost_center", "entries_without_cost_center")


class CostAttributionSource:
    source_id = "cost_attribution"

    def __init__(self, store: LedgerStore | None) -> None:
        self._store = store

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._store is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        try:
            entries = await self._store.list_entries(
                request.scope.customer_id, TimeWindow(request.window_start, request.window_end)
            )
        except Exception:
            return unavailable(self.source_id, request, "store_error", _MEASURES)
        in_domain = [e for e in entries if e.domain_id == request.domain_id]
        truncated = len(in_domain) > request.cap
        seen = in_domain[: request.cap]
        if seen and not all(hasattr(e, "cost_center") for e in seen):
            return make_observation(
                self.source_id,
                request,
                status="not_collected",
                reason_code="cost_center_absent",
                measures=dict.fromkeys(_MEASURES),
            )
        tagged = sum(1 for e in seen if e.cost_center is not None)
        latest: datetime | None = max((e.observed_at for e in seen), default=None)
        return make_observation(
            self.source_id,
            request,
            status="partial" if truncated else "observed",
            reason_code="capped" if truncated else None,
            latest_at=latest,
            truncated=truncated,
            measures={
                "records": len(seen),
                "entries_with_cost_center": tagged,
                "entries_without_cost_center": len(seen) - tagged,
            },
        )
