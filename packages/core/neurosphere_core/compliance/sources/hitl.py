"""HITL decision evidence (PRP-56 item 3).

Counts the domain's review items and the decisions taken in the window through the scope-filtered
review store. Only counts and the newest decision time leave this module: no item subject, maker,
assignee or decision reason.
"""

from __future__ import annotations

from datetime import datetime

from neurosphere_contracts.compliance.v1.evidence_observation import EvidenceObservation

from neurosphere_core.compliance.sources.base import (
    SourceRequest,
    make_observation,
    unavailable,
)
from neurosphere_core.hitl.store import HitlStore

__all__ = ["HitlDecisionsSource"]

_PAGE = 100
_MEASURES = ("records", "items_seen", "decided_approved", "decided_rejected")
_DECIDED = {"approved", "rejected", "executed", "failed"}


class HitlDecisionsSource:
    source_id = "hitl_decisions"

    def __init__(self, store: HitlStore | None) -> None:
        self._store = store

    async def observe(self, request: SourceRequest) -> EvidenceObservation:
        if self._store is None:
            return unavailable(self.source_id, request, "store_unconfigured", _MEASURES)
        seen = decided = approved = rejected = 0
        latest: datetime | None = None
        cursor: str | None = None
        truncated = False
        try:
            while True:
                page = await self._store.list(
                    request.scope, request.domain_id, cursor=cursor, limit=_PAGE
                )
                for item in page.items:
                    seen += 1
                    when = item.decided_at
                    if when is None or not request.window_start <= when < request.window_end:
                        continue
                    if item.state_name in _DECIDED or item.decision_id is not None:
                        decided += 1
                        if item.state_name == "rejected":
                            rejected += 1
                        else:
                            approved += 1
                        if latest is None or when > latest:
                            latest = when
                cursor = page.next_cursor
                if cursor is None:
                    break
                if seen >= request.cap:
                    truncated = True
                    break
        except Exception:
            return unavailable(self.source_id, request, "store_error", _MEASURES)
        return make_observation(
            self.source_id,
            request,
            status="partial" if truncated else "observed",
            reason_code="capped" if truncated else None,
            latest_at=latest,
            truncated=truncated,
            measures={
                "records": decided,
                "items_seen": seen,
                "decided_approved": approved,
                "decided_rejected": rejected,
            },
        )
