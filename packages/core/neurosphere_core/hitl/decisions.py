"""Append-only decision log over the PRP-06 hash-chained audit store (clarification 9).

Every :class:`ApprovalDecision` is written as a ``before`` / ``after`` pair on the domain's
audit chain (the record carries a digest of the decision, never its free-text reason) and stored
create-only in a :class:`DecisionStore`. A failed audit write aborts before the decision is
stored (fail closed). There is no update, delete or replace: those names exist on
:class:`DecisionLog` only to refuse with ``forbidden`` (reason ``decision_append_only``), like
``AuditRepository``. A correction is a new decision on a new review item.

Returned decisions are :class:`ImmutableDecision` instances (a frozen subclass of the contract
model) rebuilt from the stored document on every read, so no caller can alter a stored decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn, Protocol, runtime_checkable

from neurosphere_contracts.actions.v1.approval_decision import ApprovalDecision
from pydantic import ConfigDict

from neurosphere_core.audit import (
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    digests_equal,
    make_subject,
    run_audited_mutation,
    sha256_digest,
)
from neurosphere_core.audit.builders import Channel
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    StaleVersionError,
)
from neurosphere_core.hitl.auditing import (
    ENTITY_TYPE,
    audit_chain_for,
    audit_context,
    refusal_code,
)

__all__ = [
    "DecisionLog",
    "DecisionStore",
    "ImmutableDecision",
    "InMemoryDecisionStore",
    "decision_digest",
]

_MAX_PER_ITEM = 500


class ImmutableDecision(ApprovalDecision):
    """The contract ``ApprovalDecision`` with assignment refused (frozen)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def decision_digest(decision: ApprovalDecision) -> str:
    return sha256_digest(decision.model_dump(mode="json"))


def _append_only() -> NoReturn:
    raise ForbiddenError("review decisions are append-only", reason="decision_append_only")


@runtime_checkable
class DecisionStore(Protocol):
    """Create-only storage of decision documents. No update/upsert/delete exists by design."""

    async def create(self, decision_id: str, document: Mapping[str, Any]) -> None:
        """Insert; an existing ``decision_id`` is ``stale_version`` (``decision_exists``)."""
        ...

    async def get(self, decision_id: str) -> dict[str, Any] | None: ...

    async def list_for_item(self, review_item_id: str) -> list[dict[str, Any]]:
        """Decisions of one review item, in insertion order (at most 500)."""
        ...


class InMemoryDecisionStore:
    def __init__(self) -> None:
        self._docs: dict[str, str] = {}
        self._order: list[str] = []
        self.outage = False

    def _check(self) -> None:
        if self.outage:
            raise DependencyTransientError(
                "decision store unavailable", reason="hitl_store_unavailable"
            )

    async def create(self, decision_id: str, document: Mapping[str, Any]) -> None:
        self._check()
        if decision_id in self._docs:
            raise StaleVersionError("decision already recorded", reason="decision_exists")
        self._docs[decision_id] = json.dumps(dict(document), sort_keys=True)
        self._order.append(decision_id)

    async def get(self, decision_id: str) -> dict[str, Any] | None:
        self._check()
        raw = self._docs.get(decision_id)
        return None if raw is None else json.loads(raw)

    async def list_for_item(self, review_item_id: str) -> list[dict[str, Any]]:
        self._check()
        found = [json.loads(self._docs[d]) for d in self._order]
        return [doc for doc in found if doc.get("review_item_id") == review_item_id][:_MAX_PER_ITEM]


class DecisionLog:
    """``append`` plus reads. Construct with the audit repository and a decision store."""

    def __init__(self, audit: AuditRepository, store: DecisionStore) -> None:
        self._audit = audit
        self._store = store

    async def append(
        self,
        decision: ApprovalDecision,
        *,
        cloud: str,
        customer_id: str,
        domain_id: str,
        scope_hash: str,
        channel: Channel | None = "rest",
    ) -> ImmutableDecision:
        """Audit (before), store create-only, read back, audit (after). Returns the stored copy."""
        frozen = ImmutableDecision.model_validate(decision.model_dump(mode="json"))
        digest = decision_digest(frozen)
        review_item_id = frozen.review_item_id.root
        ctx = audit_context(
            actor=frozen.reviewer,
            scope_hash=scope_hash,
            correlation_id=frozen.correlation_id,
            operation=f"hitl.decision.{frozen.review_kind}",
            channel=channel,
            intent_id=None if frozen.intent_id is None else frozen.intent_id.root,
        )
        subject = make_subject(
            f"{cloud}:{customer_id}:hitl:{ENTITY_TYPE}:{review_item_id}",
            ENTITY_TYPE,
            target_version=None,
            state_digest=digest,
        )

        async def mutate() -> ImmutableDecision:
            await self._store.create(frozen.decision_id.root, frozen.model_dump(mode="json"))
            stored = await self.get(frozen.decision_id.root)
            if stored is None or not digests_equal(decision_digest(stored), digest):
                raise DependencyTransientError(
                    "stored decision could not be read back", reason="decision_unverified"
                )
            return stored

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx, subject, result="failed", verified=False, detail=refusal_code(exc)
            )

        def succeeded(_: ImmutableDecision) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail=f"decision={frozen.decision}",
            )

        return await run_audited_mutation(
            self._audit,
            audit_chain_for(customer_id, domain_id),
            before=build_before(ctx, subject),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )

    async def get(self, decision_id: str) -> ImmutableDecision | None:
        doc = await self._store.get(decision_id)
        return None if doc is None else ImmutableDecision.model_validate(doc)

    async def list_for_item(self, review_item_id: str) -> list[ImmutableDecision]:
        docs = await self._store.list_for_item(review_item_id)
        return [ImmutableDecision.model_validate(doc) for doc in docs]

    # -- refused operations ------------------------------------------------------------------

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def replace(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def upsert(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def patch(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()

    def remove(self, *args: Any, **kwargs: Any) -> NoReturn:
        _append_only()
