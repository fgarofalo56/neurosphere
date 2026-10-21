"""Review-item completion hook for the action executor (PRP-17 item 7a).

When an approved ``maker_checker`` intent reaches a terminal outcome the executor calls an
optional ``on_finished`` hook. :class:`ReviewItemCompletion` is the HITL adapter: succeeded marks
the linked review item ``executed``; failed, rolled_back or expired marks it ``failed``. The hook
is retry-safe (an item already in the target state is left alone) and never changes the intent
outcome: any failure is logged and audited by the caller side of the executor.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol

from neurosphere_core.actions import ActionAuditEvent, ActionAuditor, StoredIntent
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.hitl import SYSTEM_ACTOR, SYSTEM_SCOPE_HASH

if TYPE_CHECKING:
    from neurosphere_workers.actions.executor import ExecutionReport

__all__ = ["FinishedHook", "ReviewItemCompletion", "ReviewItemOutcomes"]

logger = logging.getLogger("neurosphere.workers.actions")

FinishedHook = Callable[[StoredIntent, "ExecutionReport"], Awaitable[None]]

_OPERATION: Final = "hitl.review.completion_hook"


def _correlation(stored: StoredIntent) -> str:
    # Short prefix only: the audit content guard rejects full GUIDs outside a few fields.
    return f"completion-{stored.intent_id[:8]}"


class _ItemState(Protocol):
    @property
    def state_name(self) -> str: ...


class ReviewItemOutcomes(Protocol):
    """The slice of ``HitlService`` the completion hook needs (structural, so tests can fake it)."""

    async def mark_executed(
        self, item_id: str, now: datetime, *, correlation_id: str
    ) -> object: ...

    async def mark_failed(self, item_id: str, now: datetime, *, correlation_id: str) -> object: ...

    async def get(self, item_id: str) -> _ItemState | None: ...


class ReviewItemCompletion:
    """Marks the review item linked to a finished intent ``executed`` or ``failed``."""

    def __init__(
        self,
        hitl: ReviewItemOutcomes,
        *,
        auditor: ActionAuditor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._hitl = hitl
        self._auditor = auditor
        self._clock = clock or (lambda: datetime.now(UTC))

    async def __call__(self, stored: StoredIntent, report: ExecutionReport) -> None:
        item_id = stored.review_item_id
        if item_id is None:
            return
        correlation_id = _correlation(stored)
        try:
            if stored.state == "succeeded":
                await self._hitl.mark_executed(
                    item_id, self._clock(), correlation_id=correlation_id
                )
            else:
                await self._hitl.mark_failed(item_id, self._clock(), correlation_id=correlation_id)
        except Exception as exc:
            if await self._already_final(item_id, stored.state):
                return
            await self._audit_failure(stored, exc)
            raise

    async def _already_final(self, item_id: str, state: str) -> bool:
        """True when a previous pass already moved the item to the matching final state."""
        try:
            item = await self._hitl.get(item_id)
        except Exception:
            return False
        return item is not None and item.state_name == (
            "executed" if state == "succeeded" else "failed"
        )

    async def _audit_failure(self, stored: StoredIntent, exc: Exception) -> None:
        if self._auditor is None:
            return
        reason = exc.reason if isinstance(exc, NeuroSphereError) and exc.reason else "hook_error"
        try:
            await self._auditor.record(
                ActionAuditEvent(
                    kind="after",
                    operation=_OPERATION,
                    actor=SYSTEM_ACTOR,
                    scope_hash=SYSTEM_SCOPE_HASH,
                    correlation_id=_correlation(stored),
                    channel=None,
                    customer_id=stored.customer_id,
                    domain_id=stored.domain_id,
                    intent_id=stored.intent_id,
                    target=stored.intent.target,
                    target_version=stored.intent.target_version,
                    result="failed",
                    reason=str(reason)[:64],
                )
            )
        except Exception:
            logger.warning(
                "completion hook audit failed",
                extra={"event": "action.completion_audit_failed", "intent_id": stored.intent_id},
            )
