"""Plan-approval repository protocol and the in-memory implementation (PRP-55 item 1).

Rules every implementation keeps (``decide``):

* approve is create-only per ``(customer_id, plan_id)``: a live approval of the same plan hash is
  returned unchanged (idempotent), a live approval of another hash refuses ``plan_id_conflict``;
* an expired approval reads as absent and may be replaced by a new approval;
* nothing is ever evicted: a record leaves only by expiry.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from neurosphere_core.deploy.approvals.models import PlanApprovalRecord, decide

__all__ = ["Clock", "InMemoryPlanApprovalRepository", "PlanApprovalRepository", "utc_now"]

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class PlanApprovalRepository(Protocol):
    """Durable approvals keyed by ``(customer_id, plan_id)``."""

    async def create(self, record: PlanApprovalRecord) -> PlanApprovalRecord:
        """Store ``record`` (create-only); returns the record now in force."""
        ...

    async def get(self, customer_id: str, plan_id: str) -> PlanApprovalRecord | None:
        """The live approval, or ``None`` (absent or expired)."""
        ...


class InMemoryPlanApprovalRepository:
    """Per-process repository with the same rules as the Cosmos one (tests, local seams)."""

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._records: dict[tuple[str, str], PlanApprovalRecord] = {}

    async def create(self, record: PlanApprovalRecord) -> PlanApprovalRecord:
        key = (record.customer_id, record.plan_id)
        kept = decide(self._records.get(key), record, self._clock())
        if kept is not None:
            return kept
        self._records[key] = record
        return record

    async def get(self, customer_id: str, plan_id: str) -> PlanApprovalRecord | None:
        found = self._records.get((customer_id, plan_id))
        if found is None or not found.live_at(self._clock()):
            return None
        return found
