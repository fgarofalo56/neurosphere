"""Curation domain service (PRP-10 item 4): steward decisions, locks and re-inference.

Rules enforced here (the generated ``EdgeOverride`` model has no Python validators, so the
schema's conditional requirements are checked explicitly):

* Preconditions: ``expected_edge_version`` and ``expected_edge_etag`` must equal the stored edge,
  else ``stale_version``. (Missing values never reach here: the body model requires them and the
  app maps a schema failure to ``invalid_schema``.)
* ``lock`` and ``override`` need ``lock.locked`` with reason, expiry and actor, and an expiry in
  the future; ``accept``, ``reject`` and ``unlock`` carry no active lock.
* The decision time is the SERVER clock; a caller-supplied ``decided_at`` is replaced so a decision
  cannot be back-dated to reorder history. The target domain, customer and cloud must equal the
  stored edge.
* The ``actor`` is the authenticated principal: it is stamped from the scope, and a different
  client value is refused with ``forbidden`` (reason ``actor_mismatch``) and audited as a denial.
* Evidence is append-only: ``add_evidence_ids`` can add, the model has no way to remove, and the
  presented union is computed by ``rules.present_edge``. Locks change presented lineage only;
  observations are always stored (``apply_inference``).
* Every action writes audit records (before/after, or denied for a refused request) on the chain
  ``<customer>.<domain>``; a failed audit write aborts the action (fail closed).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal

from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    build_denied,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.catalog import (
    CatalogEdge,
    CatalogRepository,
    PresentedEdge,
    ReviewQueue,
    format_timestamp,
    merge_observation,
    parse_timestamp,
    present_edge,
)
from neurosphere_core.catalog.rules import MergeOutcome
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    StaleVersionError,
)
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict

__all__ = ["Clock", "CurationService", "DecisionResult", "InferenceResult", "audit_chain_id"]

Clock = Callable[[], datetime]
Channel = Literal["button", "chat", "rest", "mcp", "websocket", "worker"]

_PINNING: Final = frozenset({"lock", "override"})
_ENTITY_TYPE: Final = "edge"
_VOLATILE: Final = {"updated_at", "version", "etag"}


class DecisionResult(BaseModel):
    """A stored steward decision and the presented edge after it."""

    model_config = ConfigDict(extra="forbid")

    override: EdgeOverride
    presented: PresentedEdge


class InferenceResult(BaseModel):
    """Outcome of one re-inference: presented lineage, and whether a conflict was queued."""

    model_config = ConfigDict(extra="forbid")

    presented: PresentedEdge
    presented_changed: bool
    observation_recorded: bool
    review_item_id: str | None = None
    review_enqueued: bool = False


def audit_chain_id(edge: CatalogEdge) -> str:
    """Audit chain of the edge's domain: ``<customer>.<domain name>`` (audit_mount convention)."""
    name = edge.domain_id.root.rsplit(":", 1)[-1]
    return f"{edge.customer_id.root}.{name}"


def _refusal(exc: BaseException) -> str:
    """Short machine code for an audit record: the error's reason, else its code."""
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"


def _stamp_actor(scope: IdentityScope, decision: EdgeOverride) -> EdgeOverride:
    """Stamp ``actor`` from the authenticated principal (PRP-29 item 4, Clarification 20).

    The contract requires the field, so a client still sends it; a value that is not the caller's
    own principal id is refused (``ForbiddenError``, audited as a denial by ``decide``) rather
    than silently replaced, so a steward cannot attribute a decision to someone else.
    """
    principal = scope.to_contract().principal.principal_id.root
    if decision.actor.root != principal:
        raise ForbiddenError("actor must be the authenticated principal", reason="actor_mismatch")
    actor = type(decision.actor).model_validate(principal)
    return decision.model_copy(update={"actor": actor})


def _edge_changed(before: CatalogEdge, after: CatalogEdge) -> bool:
    return before.model_dump(exclude=_VOLATILE) != after.model_dump(exclude=_VOLATILE)


class CurationService:
    """Steward decisions and re-inference over a ``CatalogRepository`` (protocol only)."""

    def __init__(
        self,
        repository: CatalogRepository,
        review_queue: ReviewQueue,
        audit: AuditRepository,
        clock: Clock,
    ) -> None:
        self._repo = repository
        self._queue = review_queue
        self._audit = audit
        self._clock = clock

    # -- reads -----------------------------------------------------------------------------

    async def presented(self, scope: IdentityScope, edge: CatalogEdge) -> PresentedEdge:
        overrides = await self._repo.list_overrides(scope, edge.id)
        return present_edge(edge, overrides, self._clock())

    async def overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        return await self._repo.list_overrides(scope, edge_id)

    # -- decisions -------------------------------------------------------------------------

    async def decide(
        self,
        scope: IdentityScope,
        edge: CatalogEdge,
        decision: EdgeOverride,
        *,
        correlation_id: str,
        channel: Channel = "rest",
    ) -> DecisionResult:
        """Validate, audit and store one steward decision on ``edge`` (the stored edge).

        The caller has already authorized ``catalog.curate`` on ``edge.domain_id``.
        """
        now = self._clock()
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation="catalog.curate", channel=channel
        )
        chain = audit_chain_id(edge)
        before = present_edge(edge, await self._repo.list_overrides(scope, edge.id), now)
        subject = make_subject(
            edge.id,
            _ENTITY_TYPE,
            target_version=str(edge.version.root),
            state=before.model_dump(mode="json"),
        )
        try:
            stamped = self._validate(edge, _stamp_actor(scope, decision), now)
        except (ForbiddenError, StaleVersionError, InvalidSchemaError) as exc:
            await self._audit.append(
                chain, build_denied(ctx, code=exc.code, reason=_refusal(exc), subject=subject)
            )
            raise

        async def mutate() -> DecisionResult:
            stored = await self._repo.put_override(scope, stamped)
            current = await self._repo.list_overrides(scope, edge.id)
            if not any(o.id == stored.id for o in current):
                raise InvalidSchemaError(
                    "stored decision could not be read back", reason="unverified"
                )
            return DecisionResult(override=stored, presented=present_edge(edge, current, now))

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(ctx, subject, result="failed", verified=False, detail=_refusal(exc))

        def succeeded(result: DecisionResult) -> AuditDraft:
            state = result.presented.model_dump(mode="json")
            return build_after(
                ctx,
                make_subject(
                    edge.id, _ENTITY_TYPE, target_version=str(edge.version.root), state=state
                ),
                result="succeeded",
                verified=True,
                detail=f"decision={result.override.decision}",
            )

        return await run_audited_mutation(
            self._audit,
            chain,
            before=build_before(ctx, subject),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )

    @staticmethod
    def _validate(edge: CatalogEdge, decision: EdgeOverride, now: datetime) -> EdgeOverride:
        if decision.edge_id != edge.id or decision.relation_type.root != edge.relation_type:
            raise InvalidSchemaError("decision does not target this edge", reason="edge_mismatch")
        if (
            decision.domain_id.root != edge.domain_id.root
            or decision.customer_id.root != edge.customer_id.root
            or decision.cloud.root != edge.cloud.root
        ):
            raise InvalidSchemaError(
                "decision domain, customer or cloud differs from the stored edge",
                reason="scope_mismatch",
            )
        if (
            decision.expected_edge_version.root != edge.version.root
            or decision.expected_edge_etag.root != edge.etag.root
        ):
            raise StaleVersionError("edge changed since it was read", reason="stale_edge")

        lock = decision.lock
        if decision.decision in _PINNING:
            if (
                lock is None
                or lock.locked is not True
                or lock.reason is None
                or lock.expiry is None
                or lock.actor is None
            ):
                raise InvalidSchemaError(
                    "a lock requires locked=true, reason, expiry and actor",
                    reason="lock_requires_reason_and_expiry",
                )
            if parse_timestamp(lock.expiry.root) <= now:
                raise InvalidSchemaError(
                    "lock expiry must be in the future", reason="lock_expiry_not_in_future"
                )
        elif lock is not None and lock.locked:
            raise InvalidSchemaError(
                f"decision {decision.decision} cannot carry an active lock",
                reason="lock_not_allowed",
            )
        if decision.decision not in _PINNING and (
            decision.set_confidence is not None or decision.set_validity is not None
        ):
            raise InvalidSchemaError(
                "set_confidence and set_validity apply to lock and override only",
                reason="pin_not_allowed",
            )
        validity = decision.set_validity
        if (
            validity is not None
            and validity.valid_to is not None
            and parse_timestamp(validity.valid_to.root) <= parse_timestamp(validity.valid_from.root)
        ):
            raise InvalidSchemaError("valid_to must be after valid_from", reason="bad_validity")

        # The decision time is the server's; the caller's value is not trusted.
        decided_at = decision.decided_at.model_copy(update={"root": format_timestamp(now)})
        return decision.model_copy(update={"decided_at": decided_at})

    # -- inference -------------------------------------------------------------------------

    async def apply_inference(
        self,
        scope: IdentityScope,
        observation: CatalogEdge,
        *,
        correlation_id: str = "worker",
    ) -> InferenceResult:
        """Merge a re-inferred edge observation without touching curated presentation.

        The raw observation is always stored. A locked edge keeps its presented state; a
        contradiction with a lock or a curated reject is queued for a steward (PRP-17).
        Authorization is the repository's scope check; callers are workers with a worker scope.
        Merges that change nothing visible are not audited (volume); conflicts and presented
        changes are.
        """
        now = self._clock()
        existing = await self._repo.get_edge(scope, observation.id)
        overrides = await self._repo.list_overrides(scope, observation.id) if existing else ()
        outcome = merge_observation(existing, observation, overrides, now)

        if outcome.review_item is None and not outcome.presented_changed:
            return await self._persist(scope, existing, outcome)
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation="catalog.infer", channel="worker"
        )
        subject = make_subject(
            observation.id,
            _ENTITY_TYPE,
            target_version=str(existing.version.root) if existing else None,
            state=(outcome.presented_before or outcome.presented).model_dump(mode="json"),
        )

        def succeeded(result: InferenceResult) -> AuditDraft:
            return build_after(
                ctx,
                make_subject(
                    observation.id,
                    _ENTITY_TYPE,
                    state=result.presented.model_dump(mode="json"),
                ),
                result="succeeded",
                verified=result.observation_recorded or result.review_enqueued,
                detail="conflict_queued" if result.review_item_id else "merged",
            )

        return await run_audited_mutation(
            self._audit,
            audit_chain_id(observation),
            before=build_before(ctx, subject),
            mutate=lambda: self._persist(scope, existing, outcome),
            after=succeeded,
            on_error=lambda exc: build_after(
                ctx, subject, result="failed", verified=False, detail=_refusal(exc)
            ),
        )

    async def _persist(
        self, scope: IdentityScope, existing: CatalogEdge | None, outcome: MergeOutcome
    ) -> InferenceResult:
        if existing is None:
            await self._repo.put_edge(scope, outcome.stored, None)
        elif _edge_changed(existing, outcome.stored):
            await self._repo.put_edge(scope, outcome.stored, existing.etag.root)
        recorded = await self._repo.record_observation(scope, outcome.observation)
        enqueued = False
        item_id: str | None = None
        if outcome.review_item is not None:
            item_id = outcome.review_item.id
            enqueued = await self._queue.enqueue(scope, outcome.review_item)
        return InferenceResult(
            presented=outcome.presented,
            presented_changed=outcome.presented_changed,
            observation_recorded=recorded,
            review_item_id=item_id,
            review_enqueued=enqueued,
        )
