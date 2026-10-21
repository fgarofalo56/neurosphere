"""``ActionService``: the ONLY code that changes ``ActionIntent`` state (PRP-17 item 1).

Every surface (button, chat, REST, MCP) and the executor worker go through this service, so the
allowlist, the confirmation binding, the maker rule, the execution-time rechecks, the kill
switch and the audit trail are enforced in one place.

Transitions are written as: audit ``before`` -> ETag-conditional store replace -> audit
``after``. A failed audit write aborts before the store write (fail closed); a concurrent writer
loses with ``stale_version`` reason ``intent_modified``, so one intent can enter ``executing``
once only. Refusals are audited as ``denied`` records before they are raised.

Error mapping (delta D3; the PRP's ``validation_error`` is ``invalid_schema``): see
:mod:`neurosphere_core.actions.errors`. Notable choices:

* A hash mismatch at confirm/approval refuses WITHOUT changing state (nothing executes; a stale
  page may simply retry with the presented hash).
* A permission denial for the CALLER (maker at confirm, approver at approval) refuses without a
  state change (an unauthorized caller must not be able to kill an intent). A revoked MAKER
  permission found at approval or at execution fails the intent (``permission_revoked``).
* An expired confirmation moves the intent to ``expired`` and raises ``stale_version``
  ``confirmation_expired``; a changed target version moves it to ``failed`` and raises
  ``stale_version`` ``target_version_changed``.
* Advisory intents refuse confirm/approval with ``capability_unavailable``
  ``advisory_connector`` and no state change.
* Prerequisite status ``unknown`` fails validation (never coerced to passed).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, NoReturn

from neurosphere_contracts.actions.v1.action_intent import ActionIntent, PrerequisiteResult
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from pydantic import ValidationError

from neurosphere_core.actions.audit import ActionAuditEvent, ActionAuditor
from neurosphere_core.actions.control import ExecutionControl, require_execution_enabled
from neurosphere_core.actions.errors import (
    ADVISORY_CONNECTOR,
    CONFIRMATION_EXPIRED,
    CONFIRMATION_HASH_MISMATCH,
    NOT_MAKER,
    PERMISSION_REVOKED,
    POLICY_STORE_UNAVAILABLE,
    SELF_APPROVAL_PROHIBITED,
    TARGET_VERSION_CHANGED,
    ActionValidationError,
    IntentNotFoundError,
    InvalidTransitionError,
)
from neurosphere_core.actions.hashing import (
    compute_confirmation_hash,
    confirmation_hashes_equal,
    diff_to_wire,
    intent_digest,
    intent_to_wire,
    validate_proposed_diff,
)
from neurosphere_core.actions.models import (
    ActionCaller,
    CreateOutcome,
    DraftRequest,
    ExecutionRecord,
    IntentKey,
    StoredIntent,
    compute_payload_digest,
    format_expiry,
    format_timestamp,
    parse_timestamp,
)
from neurosphere_core.actions.permissions import PermissionRechecker
from neurosphere_core.actions.state_machine import (
    CONFIRMATION_BOUND_STATES,
    assert_transition,
)
from neurosphere_core.actions.store import IntentStore, idempotency_reused
from neurosphere_core.audit.builders import OutcomeResult
from neurosphere_core.audit.canonical import digests_equal
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    StaleVersionError,
    ValidationIssue,
)

__all__ = [
    "APPROVE_PERMISSION",
    "DEFAULT_CONFIRMATION_TTL",
    "DEFAULT_DRAFT_RETENTION",
    "DEFAULT_EXECUTION_LEASE",
    "DEFAULT_VALIDATION_TTL",
    "EXECUTE_PERMISSION",
    "ActionService",
]

SCHEMA_VERSION: Final = "1.0.0"
EXECUTE_PERMISSION: Final = "action.execute"
APPROVE_PERMISSION: Final = "action.approve"
DEFAULT_CONFIRMATION_TTL: Final = timedelta(minutes=15)
MIN_CONFIRMATION_TTL: Final = timedelta(seconds=30)
MAX_CONFIRMATION_TTL: Final = timedelta(days=7)
DEFAULT_DRAFT_RETENTION: Final = timedelta(hours=24)
DEFAULT_VALIDATION_TTL: Final = timedelta(hours=24)
DEFAULT_EXECUTION_LEASE: Final = timedelta(minutes=5)
_EXPIRABLE: Final = ("drafted", "validated", "awaiting_confirmation", "awaiting_approval")
_EXPIRY_REASON: Final = {
    "drafted": "draft_abandoned",
    "validated": "validation_stale",
    "awaiting_confirmation": CONFIRMATION_EXPIRED,
    "awaiting_approval": CONFIRMATION_EXPIRED,
}
_DEFAULT_FAILURE_REASON: Final = {
    "failed": "execution_failed",
    "rolled_back": "verification_failed",
}

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
ExecutionOutcome = Literal["succeeded", "failed", "rolled_back"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid4() -> str:
    return str(uuid.uuid4())


def _ceil_to_second(instant: datetime) -> datetime:
    if instant.microsecond == 0:
        return instant
    return instant.replace(microsecond=0) + timedelta(seconds=1)


def _result_for(state: str) -> OutcomeResult:
    if state in ("failed", "expired"):
        return "failed"
    if state == "rolled_back":
        return "rolled_back"
    return "succeeded"


def _require_state(stored: StoredIntent, expected: str, target: str) -> None:
    """Each operation has ONE legal source state; the allowlist alone is not enough.

    (``awaiting_approval -> executing`` is allowlisted, so without this a ``confirm`` call
    could skip approval.)
    """
    if stored.state != expected:
        raise InvalidTransitionError(stored.state, target)
    assert_transition(expected, target)


def _reason_of(exc: NeuroSphereError) -> str:
    return exc.reason if isinstance(exc.reason, str) and exc.reason else exc.code


class ActionService:
    """Draft, validate, confirm, approve, execute bookkeeping and expiry for action intents.

    All methods are async and take an optional ``now`` (defaults to the injected clock).
    ``customer_id``/``domain_id`` must come from the server-derived ``IdentityScope`` (the API
    authorizes the domain before calling); the service never trusts them from a body.
    """

    def __init__(
        self,
        store: IntentStore,
        *,
        auditor: ActionAuditor,
        rechecker: PermissionRechecker,
        execution_control: ExecutionControl | None = None,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _uuid4,
        confirmation_ttl: timedelta = DEFAULT_CONFIRMATION_TTL,
        draft_retention: timedelta = DEFAULT_DRAFT_RETENTION,
        validation_ttl: timedelta = DEFAULT_VALIDATION_TTL,
    ) -> None:
        self._store = store
        self._auditor = auditor
        self._rechecker = rechecker
        self._control = execution_control
        self._clock = clock
        self._ids = id_factory
        self._confirmation_ttl = self._checked_ttl(confirmation_ttl)
        self._draft_retention = draft_retention
        self._validation_ttl = validation_ttl

    # -- reads -------------------------------------------------------------------------------

    async def get(self, key: IntentKey) -> StoredIntent:
        """The stored intent, or :class:`IntentNotFoundError`."""
        found = await self._store.get(key.customer_id, key.domain_id, key.intent_id)
        if found is None:
            raise IntentNotFoundError(key.intent_id)
        return found

    # -- draft -------------------------------------------------------------------------------

    async def draft(
        self,
        caller: ActionCaller,
        request: DraftRequest,
        *,
        customer_id: str,
        domain_id: str,
        now: datetime | None = None,
    ) -> CreateOutcome:
        """Create a ``drafted`` intent, or return the original for a replayed idempotency key.

        Same ``(principal_id, idempotency_key)`` and same payload -> the original intent with
        ``created=False`` (nothing written, nothing audited). Same key, different payload ->
        ``invalid_schema`` ``idempotency_key_reused`` (audited).
        """
        at = self._now(now)
        validate_proposed_diff(request.proposed_diff)
        digest = compute_payload_digest(request, customer_id=customer_id, domain_id=domain_id)
        refusal_parts: dict[str, Any] = {
            "customer_id": customer_id,
            "domain_id": domain_id,
            "intent_id": None,
            "target": request.target,
            "target_version": request.target_version,
        }
        try:
            self._check_target_scope(request.target, customer_id, domain_id)
        except ForbiddenError as exc:
            await self._record_denial(caller, "action.draft", exc, **refusal_parts)
            raise
        existing = await self._store.find_by_idempotency_key(
            caller.principal_id, request.idempotency_key, customer_id=customer_id
        )
        if existing is not None:
            if not digests_equal(existing.payload_digest, digest):
                exc = idempotency_reused()
                await self._record_denial(caller, "action.draft", exc, **refusal_parts)
                raise exc
            return CreateOutcome(stored=existing, created=False)

        timestamp = format_timestamp(at)
        intent = self._validate_intent(
            {
                "schema_version": SCHEMA_VERSION,
                "intent_id": self._ids(),
                "action_kind": request.action_kind,
                "actor": caller.actor.model_dump(mode="json"),
                "target": request.target.model_dump(mode="json"),
                "target_version": request.target_version,
                "proposed_diff": diff_to_wire(request.proposed_diff),
                "prerequisite_results": [],
                "evidence": [e.model_dump(mode="json") for e in request.evidence],
                "confirmation_hash": None,
                "confirmation_expires_at": None,
                "idempotency_key": request.idempotency_key,
                "channel": request.channel,
                "state": "drafted",
                "status_reason": None,
                "dry_run": request.dry_run,
                "correlation_id": caller.correlation_id,
                "created_at": timestamp,
                "state_changed_at": timestamp,
            }
        )
        stored = StoredIntent(
            intent=intent,
            principal_id=caller.principal_id,
            customer_id=customer_id,
            domain_id=domain_id,
            scope_hash=caller.scope_hash,
            payload_digest=digest,
            due_at=at + self._draft_retention,
        )
        await self._auditor.record(
            self._event(stored, caller, "action.draft", "before", to_state="drafted")
        )
        outcome = await self._store.create(stored)
        if outcome.created:
            await self._auditor.record(
                self._event(
                    outcome.stored,
                    caller,
                    "action.draft",
                    "after",
                    to_state="drafted",
                    result="succeeded",
                    state_digest=intent_digest(outcome.stored.intent),
                )
            )
        return outcome

    # -- validate ----------------------------------------------------------------------------

    async def record_validation(
        self,
        key: IntentKey,
        caller: ActionCaller,
        prerequisite_results: Sequence[PrerequisiteResult],
        *,
        advisory: bool = False,
        now: datetime | None = None,
    ) -> StoredIntent:
        """``drafted`` -> ``validated`` (no failed/unknown check) or ``failed``.

        ``advisory`` is the write connector's flag from its dry run; an advisory intent may be
        validated and reviewed but can never be confirmed or approved.
        """
        at = self._now(now)
        stored = await self.get(key)
        _require_state(stored, "drafted", "validated")
        results = [r.model_dump(mode="json") for r in prerequisite_results]
        statuses = {r.status for r in prerequisite_results}
        if "failed" in statuses:
            target, reason = "failed", "prerequisite_failed"
        elif "unknown" in statuses:
            target, reason = "failed", "prerequisite_unknown"
        else:
            target, reason = "validated", None
        return await self._transition(
            stored,
            target,
            caller=caller,
            operation="action.validate",
            reason=reason,
            now=at,
            intent_updates={"prerequisite_results": results},
            envelope_updates={"advisory": advisory},
        )

    # -- confirmation ------------------------------------------------------------------------

    async def present_confirmation(
        self,
        key: IntentKey,
        caller: ActionCaller,
        *,
        current_target_version: str | None = None,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> StoredIntent:
        """``validated`` -> ``awaiting_confirmation``; binds hash and expiry (maker only).

        The expiry is ``now + ttl`` rounded up to a whole second; the returned intent carries the
        ``confirmation_hash`` the confirm call must echo. A ``current_target_version`` that
        differs from the drafted one fails the intent (``target_version_changed``).
        """
        at = self._now(now)
        stored = await self.get(key)
        operation = "action.confirmation"
        _require_state(stored, "validated", "awaiting_confirmation")
        await self._require_maker(stored, caller, operation)
        await self._check_version(stored, caller, operation, current_target_version, at)
        lifetime = self._checked_ttl(ttl) if ttl is not None else self._confirmation_ttl
        expires_at = format_expiry(_ceil_to_second(at + lifetime))
        wire = intent_to_wire(stored.intent)
        wire["confirmation_expires_at"] = expires_at
        return await self._transition(
            stored,
            "awaiting_confirmation",
            caller=caller,
            operation=operation,
            now=at,
            intent_updates={
                "confirmation_expires_at": expires_at,
                "confirmation_hash": compute_confirmation_hash(wire),
            },
        )

    async def confirm(
        self,
        key: IntentKey,
        caller: ActionCaller,
        *,
        confirmation_hash: str,
        current_target_version: str,
        requires_approval: bool,
        advisory: bool,
        permission: str = EXECUTE_PERMISSION,
        now: datetime | None = None,
    ) -> StoredIntent:
        """``awaiting_confirmation`` -> ``awaiting_approval`` or ``executing`` (maker only).

        Order: state, advisory, maker, expiry, hash, permission recheck, emergency disable
        (only when going straight to ``executing``), target version.
        """
        at = self._now(now)
        stored = await self.get(key)
        operation = "action.confirm"
        target = "awaiting_approval" if requires_approval else "executing"
        _require_state(stored, "awaiting_confirmation", target)
        await self._refuse_advisory(stored, caller, operation, advisory)
        await self._require_maker(stored, caller, operation)
        await self._check_expiry(stored, caller, operation, at)
        await self._check_hash(stored, caller, operation, confirmation_hash)
        await self._recheck(stored, caller, operation, caller.principal_id, permission)
        if target == "executing":
            await self._check_enabled(stored, caller, operation)
        await self._check_version(stored, caller, operation, current_target_version, at)
        updates: dict[str, Any] = {"requires_approval": requires_approval}
        if target == "executing":
            updates["execution"] = ExecutionRecord(updated_at=at)
        return await self._transition(
            stored, target, caller=caller, operation=operation, now=at, envelope_updates=updates
        )

    async def decline(
        self,
        key: IntentKey,
        caller: ActionCaller,
        *,
        reason: str = "declined_by_actor",
        now: datetime | None = None,
    ) -> StoredIntent:
        """``awaiting_confirmation`` -> ``failed``: the maker declined."""
        at = self._now(now)
        stored = await self.get(key)
        _require_state(stored, "awaiting_confirmation", "failed")
        await self._require_maker(stored, caller, "action.decline")
        return await self._transition(
            stored, "failed", caller=caller, operation="action.decline", reason=reason, now=at
        )

    # -- approval ----------------------------------------------------------------------------

    async def apply_approval(
        self,
        key: IntentKey,
        caller: ActionCaller,
        *,
        approved: bool,
        approved_confirmation_hash: str,
        current_target_version: str,
        self_approval_forbidden: bool = True,
        permission: str = APPROVE_PERMISSION,
        rejection_reason: str = "approval_rejected",
        now: datetime | None = None,
    ) -> StoredIntent:
        """Apply a maker-checker decision: ``awaiting_approval`` -> ``executing`` or ``failed``.

        The HITL layer decides eligibility; this method re-enforces it: the approver's
        ``permission`` is rechecked, self-approval is refused when forbidden (real principal
        ids), the decision must carry the bound hash, and on approval the maker's
        ``action.execute`` and the target version are rechecked again.
        """
        at = self._now(now)
        stored = await self.get(key)
        operation = "action.approve"
        _require_state(stored, "awaiting_approval", "executing" if approved else "failed")
        await self._refuse_advisory(stored, caller, operation, False)
        if self_approval_forbidden and caller.principal_id == stored.principal_id:
            await self._deny(
                stored,
                caller,
                operation,
                ForbiddenError(
                    "the maker cannot approve this change", reason=SELF_APPROVAL_PROHIBITED
                ),
            )
        await self._recheck(stored, caller, operation, caller.principal_id, permission)
        await self._check_expiry(stored, caller, operation, at)
        await self._check_hash(stored, caller, operation, approved_confirmation_hash)
        if not approved:
            return await self._transition(
                stored,
                "failed",
                caller=caller,
                operation=operation,
                reason=rejection_reason,
                now=at,
            )
        if not await self._permitted(stored, caller, operation, stored.principal_id):
            await self._fail_and_raise(
                stored,
                caller,
                operation,
                at,
                ForbiddenError(
                    "the maker no longer holds the permission", reason=PERMISSION_REVOKED
                ),
            )
        await self._check_enabled(stored, caller, operation)
        await self._check_version(stored, caller, operation, current_target_version, at)
        return await self._transition(
            stored,
            "executing",
            caller=caller,
            operation=operation,
            now=at,
            envelope_updates={"execution": ExecutionRecord(updated_at=at)},
        )

    async def link_review_item(self, key: IntentKey, review_item_id: str) -> StoredIntent:
        """Attach the maker-checker review item id (no state change; ``awaiting_approval``)."""
        stored = await self.get(key)
        if stored.state != "awaiting_approval":
            raise ActionValidationError(
                "review_link_not_allowed", "intent is not awaiting approval"
            )
        return await self._store.replace(
            stored.model_copy(update={"review_item_id": review_item_id}),
            if_match=self._etag(stored),
        )

    # -- execution (used by the executor worker, PRP-17 item 2) --------------------------------

    async def begin_execution(
        self,
        key: IntentKey,
        *,
        worker_id: str,
        lease: timedelta = DEFAULT_EXECUTION_LEASE,
        now: datetime | None = None,
    ) -> StoredIntent:
        """Claim an ``executing`` intent: lease it to ``worker_id`` and count the attempt.

        Raises ``capability_unavailable`` ``emergency_disabled`` (or ``dependency_transient``
        when the control store is down) without touching the intent; ``stale_version``
        ``execution_leased`` while another worker's lease is live; ``stale_version``
        ``intent_modified`` when another worker claimed it first. Inspect
        ``execution.apply_may_have_happened()`` on the result: when True, resume with verify.
        """
        at = self._now(now)
        stored = await self.get(key)
        if stored.state != "executing":
            raise InvalidTransitionError(stored.state, "executing")
        worker = ActionCaller.for_worker(stored)
        await self._check_enabled(stored, worker, "action.execute")
        record = stored.execution or ExecutionRecord()
        if (
            record.lease_owner is not None
            and record.lease_owner != worker_id
            and record.lease_expires_at is not None
            and record.lease_expires_at > at
        ):
            raise StaleVersionError(
                "intent is leased by another executor", reason="execution_leased"
            )
        claimed = record.model_copy(
            update={
                "attempts": record.attempts + 1,
                "lease_owner": worker_id,
                "lease_expires_at": at + lease,
                "updated_at": at,
            }
        )
        return await self._store.replace(
            stored.model_copy(update={"execution": claimed}), if_match=self._etag(stored)
        )

    async def recheck_execution(
        self,
        stored: StoredIntent,
        *,
        current_target_version: str,
        now: datetime | None = None,
    ) -> StoredIntent:
        """Execution-time recheck before any apply; records phase ``rechecked``.

        Kill switch (raises, intent untouched), stored binding integrity, the MAKER's current
        ``action.execute`` (revoked -> ``failed`` ``permission_revoked``, audited) and the target
        version (changed -> ``failed`` ``target_version_changed``). Refused once an apply may
        have happened: from then on recovery verifies, it never re-decides.
        """
        at = self._now(now)
        worker = ActionCaller.for_worker(stored)
        operation = "action.execute"
        if stored.state != "executing":
            raise InvalidTransitionError(stored.state, "executing")
        record = stored.execution or ExecutionRecord()
        if record.apply_may_have_happened():
            raise ActionValidationError("recheck_after_apply", "apply may already have happened")
        await self._check_enabled(stored, worker, operation)
        bound = stored.intent.confirmation_hash
        if bound is None or not confirmation_hashes_equal(
            bound.root, compute_confirmation_hash(stored.intent)
        ):
            await self._fail_and_raise(
                stored,
                worker,
                operation,
                at,
                ActionValidationError(CONFIRMATION_HASH_MISMATCH, "stored binding does not match"),
            )
        if not await self._permitted(stored, worker, operation, stored.principal_id):
            await self._fail_and_raise(
                stored,
                worker,
                operation,
                at,
                ForbiddenError(
                    "the maker no longer holds the permission", reason=PERMISSION_REVOKED
                ),
            )
        await self._check_version(stored, worker, operation, current_target_version, at)
        return await self.record_execution(
            stored, record.model_copy(update={"phase": "rechecked", "rechecked_at": at}), now=at
        )

    async def record_execution(
        self,
        stored: StoredIntent,
        execution: ExecutionRecord,
        *,
        audit: Literal["before", "after"] | None = None,
        target_state_digest: str | None = None,
        result: OutcomeResult | None = None,
        verified: bool = False,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> StoredIntent:
        """Persist executor progress on an ``executing`` intent (ETag-conditional).

        ``audit="before"`` appends a ``before`` record (with the captured TARGET state digest)
        BEFORE the write, e.g. ahead of ``apply``; ``audit="after"`` appends an ``after`` record
        once the write is durable (``result``/``verified`` describe the phase outcome).
        """
        at = self._now(now)
        if stored.state != "executing":
            raise InvalidTransitionError(stored.state, "executing")
        worker = ActionCaller.for_worker(stored)
        record = execution.model_copy(update={"updated_at": at})
        fields: dict[str, Any] = {
            "phase": record.phase,
            "state_digest": target_state_digest,
            "reason": reason,
        }
        if audit == "before":
            await self._auditor.record(
                self._event(stored, worker, "action.execute", "before", **fields)
            )
        saved = await self._store.replace(
            stored.model_copy(update={"execution": record}), if_match=self._etag(stored)
        )
        if audit == "after":
            await self._auditor.record(
                self._event(
                    saved,
                    worker,
                    "action.execute",
                    "after",
                    result=result or "succeeded",
                    verified=verified,
                    **fields,
                )
            )
        return saved

    async def finish_execution(
        self,
        stored: StoredIntent,
        *,
        outcome: ExecutionOutcome,
        reason: str | None = None,
        execution: ExecutionRecord | None = None,
        now: datetime | None = None,
    ) -> StoredIntent:
        """``executing`` -> ``succeeded`` / ``failed`` / ``rolled_back``.

        ``succeeded`` requires a recorded apply result and ``verify_matched is True`` (except
        for ``dry_run`` intents): success evidence is the connector's verification, never
        metadata. ``rolled_back`` requires ``rolled_back=True``. Failure states need a reason
        (defaults ``execution_failed`` / ``verification_failed``; use ``rollback_failed`` when
        the rollback itself failed).
        """
        at = self._now(now)
        if stored.state != "executing":
            raise InvalidTransitionError(stored.state, outcome)
        record = execution or stored.execution or ExecutionRecord()
        if outcome == "succeeded" and not stored.intent.dry_run:
            if record.apply_result is None or record.verify_matched is not True:
                raise ActionValidationError(
                    "unverified_outcome", "success requires an applied and verified change"
                )
        if outcome == "rolled_back" and not record.rolled_back:
            raise ActionValidationError("rollback_not_recorded", "no completed rollback recorded")
        final_reason = (
            reason if outcome == "succeeded" else reason or _DEFAULT_FAILURE_REASON[outcome]
        )
        done = record.model_copy(
            update={
                "phase": "done",
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error": record.last_error if outcome == "succeeded" else final_reason,
                "updated_at": at,
            }
        )
        return await self._transition(
            stored,
            outcome,
            caller=ActionCaller.for_worker(stored),
            operation="action.execute",
            reason=final_reason,
            now=at,
            envelope_updates={"execution": done},
            verified=outcome == "succeeded" and done.verify_matched is True,
        )

    # -- expiry ------------------------------------------------------------------------------

    async def expire_due(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> list[StoredIntent]:
        """Move every intent whose ``due_at`` passed to ``expired``; returns those moved.

        Intents changed concurrently (``stale_version``) or already moved on are skipped; the
        next sweep sees their new state.
        """
        at = self._now(now)
        due = await self._store.list_in_states(_EXPIRABLE, due_before=at, limit=limit)
        expired: list[StoredIntent] = []
        for stored in due:
            try:
                expired.append(
                    await self._transition(
                        stored,
                        "expired",
                        caller=ActionCaller.for_worker(stored),
                        operation="action.expire",
                        reason=_EXPIRY_REASON[stored.state],
                        now=at,
                    )
                )
            except (StaleVersionError, InvalidTransitionError):
                continue
        return expired

    # -- guards ------------------------------------------------------------------------------

    def _now(self, now: datetime | None) -> datetime:
        at = now if now is not None else self._clock()
        if at.tzinfo is None:
            raise ValueError("ActionService needs timezone-aware instants")
        return at.astimezone(UTC)

    @staticmethod
    def _checked_ttl(ttl: timedelta) -> timedelta:
        if not MIN_CONFIRMATION_TTL <= ttl <= MAX_CONFIRMATION_TTL:
            raise ActionValidationError("invalid_confirmation_ttl", "confirmation ttl out of range")
        return ttl

    @staticmethod
    def _etag(stored: StoredIntent) -> str:
        if stored.etag is None:
            raise ValueError("intent has no store etag; read it from the store first")
        return stored.etag

    @staticmethod
    def _check_target_scope(target: TargetRef, customer_id: str, domain_id: str) -> None:
        """The target must belong to the caller's customer and cloud (no cross-cloud bridge)."""
        cloud, customer = target.canonical_id.split(":", 2)[:2]
        domain_parts = domain_id.split(":")
        if customer != customer_id or (len(domain_parts) > 1 and domain_parts[0] != cloud):
            raise ForbiddenError(
                "target is outside the caller's scope", reason="target_out_of_scope"
            )

    async def _require_maker(self, stored: StoredIntent, caller: ActionCaller, op: str) -> None:
        if caller.principal_id != stored.principal_id:
            await self._deny(
                stored, caller, op, ForbiddenError("only the maker may do this", reason=NOT_MAKER)
            )

    async def _refuse_advisory(
        self, stored: StoredIntent, caller: ActionCaller, op: str, advisory: bool
    ) -> None:
        if advisory or stored.advisory:
            await self._deny(
                stored,
                caller,
                op,
                CapabilityUnavailableError(
                    ADVISORY_CONNECTOR, "the write connector is advisory; nothing can execute"
                ),
            )

    async def _check_expiry(
        self, stored: StoredIntent, caller: ActionCaller, op: str, at: datetime
    ) -> None:
        expires = stored.intent.confirmation_expires_at
        if expires is None or at >= parse_timestamp(expires.root):
            await self._transition(
                stored, "expired", caller=caller, operation=op, reason=CONFIRMATION_EXPIRED, now=at
            )
            raise StaleVersionError("the confirmation has expired", reason=CONFIRMATION_EXPIRED)

    async def _check_hash(
        self, stored: StoredIntent, caller: ActionCaller, op: str, supplied: str
    ) -> None:
        expected = compute_confirmation_hash(stored.intent)
        bound = stored.intent.confirmation_hash
        if (
            bound is None
            or not confirmation_hashes_equal(bound.root, expected)
            or not confirmation_hashes_equal(supplied, expected)
        ):
            await self._deny(
                stored,
                caller,
                op,
                ActionValidationError(
                    CONFIRMATION_HASH_MISMATCH, "confirmation does not match the bound intent"
                ),
            )

    async def _check_version(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        op: str,
        current: str | None,
        at: datetime,
    ) -> None:
        if current is not None and current != stored.intent.target_version:
            await self._fail_and_raise(
                stored,
                caller,
                op,
                at,
                StaleVersionError(
                    "the target changed since the diff", reason=TARGET_VERSION_CHANGED
                ),
            )

    async def _check_enabled(self, stored: StoredIntent, caller: ActionCaller, op: str) -> None:
        if self._control is None:
            return
        try:
            await require_execution_enabled(self._control, stored.customer_id)
        except NeuroSphereError as exc:
            await self._deny(stored, caller, op, exc)

    async def _permitted(
        self, stored: StoredIntent, caller: ActionCaller, op: str, principal_id: str
    ) -> bool:
        """Maker recheck for ``action.execute``; outage is audited and raised (fail closed)."""
        return await self._ask(stored, caller, op, principal_id, EXECUTE_PERMISSION)

    async def _recheck(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        op: str,
        principal_id: str,
        permission: str,
    ) -> None:
        """Caller recheck: a denial is audited and raised WITHOUT changing state."""
        if not await self._ask(stored, caller, op, principal_id, permission):
            await self._deny(
                stored,
                caller,
                op,
                ForbiddenError("permission was not granted at recheck", reason=PERMISSION_REVOKED),
            )

    async def _ask(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        op: str,
        principal_id: str,
        permission: str,
    ) -> bool:
        try:
            return await self._rechecker.check(
                principal_id, stored.customer_id, stored.domain_id, permission
            )
        except NeuroSphereError as exc:
            await self._deny(stored, caller, op, exc)
        except Exception as exc:
            outage = DependencyTransientError(
                "policy store unavailable", reason=POLICY_STORE_UNAVAILABLE
            )
            outage.__cause__ = exc
            await self._deny(stored, caller, op, outage)

    async def _deny(
        self, stored: StoredIntent, caller: ActionCaller, op: str, exc: NeuroSphereError
    ) -> NoReturn:
        """Audit a refusal (no state change) and raise it. Audit failure raises instead."""
        await self._record_denial(
            caller,
            op,
            exc,
            customer_id=stored.customer_id,
            domain_id=stored.domain_id,
            intent_id=stored.intent_id,
            target=stored.intent.target,
            target_version=stored.intent.target_version,
        )
        raise exc

    async def _fail_and_raise(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        op: str,
        at: datetime,
        exc: NeuroSphereError,
    ) -> NoReturn:
        """Audit the refusal, move the intent to ``failed`` with the error's reason, raise."""
        await self._record_denial(
            caller,
            op,
            exc,
            customer_id=stored.customer_id,
            domain_id=stored.domain_id,
            intent_id=stored.intent_id,
            target=stored.intent.target,
            target_version=stored.intent.target_version,
        )
        await self._transition(
            stored, "failed", caller=caller, operation=op, reason=_reason_of(exc), now=at
        )
        raise exc

    async def _record_denial(
        self,
        caller: ActionCaller,
        op: str,
        exc: NeuroSphereError,
        *,
        customer_id: str,
        domain_id: str,
        intent_id: str | None,
        target: TargetRef,
        target_version: str | None,
    ) -> None:
        await self._auditor.record(
            ActionAuditEvent(
                kind="denied",
                operation=op,
                actor=caller.actor,
                scope_hash=caller.scope_hash,
                correlation_id=caller.correlation_id,
                channel=caller.channel,
                customer_id=customer_id,
                domain_id=domain_id,
                intent_id=intent_id,
                target=target,
                target_version=target_version,
                denial_code=exc.code,
                reason=_reason_of(exc),
            )
        )

    # -- transition core -----------------------------------------------------------------------

    def _event(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        operation: str,
        kind: Literal["before", "after", "denied"],
        **fields: Any,
    ) -> ActionAuditEvent:
        return ActionAuditEvent(
            kind=kind,
            operation=operation,
            actor=caller.actor,
            scope_hash=caller.scope_hash,
            correlation_id=caller.correlation_id,
            channel=caller.channel,
            customer_id=stored.customer_id,
            domain_id=stored.domain_id,
            intent_id=stored.intent_id,
            target=stored.intent.target,
            target_version=stored.intent.target_version,
            **fields,
        )

    def _due_at(self, intent: ActionIntent, at: datetime) -> datetime | None:
        state = intent.state.root
        if state == "drafted":
            return at + self._draft_retention
        if state == "validated":
            return at + self._validation_ttl
        if state in ("awaiting_confirmation", "awaiting_approval"):
            expires = intent.confirmation_expires_at
            return parse_timestamp(expires.root) if expires is not None else at
        return None

    @staticmethod
    def _validate_intent(wire: Mapping[str, Any]) -> ActionIntent:
        try:
            intent = ActionIntent.model_validate(dict(wire))
        except ValidationError as exc:
            raise ActionValidationError(
                "invalid_intent",
                "intent does not satisfy the ActionIntent contract",
                errors=[
                    ValidationIssue("/" + "/".join(str(p) for p in err["loc"]), str(err["type"]))
                    for err in exc.errors(include_input=False, include_url=False)
                ],
            ) from exc
        state = intent.state.root
        if state in CONFIRMATION_BOUND_STATES and (
            intent.confirmation_hash is None or intent.confirmation_expires_at is None
        ):
            raise ActionValidationError("invalid_intent", "confirmation binding missing")
        if state in ("validated", *CONFIRMATION_BOUND_STATES) and any(
            r.status == "failed" for r in intent.prerequisite_results
        ):
            raise ActionValidationError("invalid_intent", "failed prerequisite on a live intent")
        if state in ("failed", "rolled_back", "expired") and intent.status_reason is None:
            raise ActionValidationError("invalid_intent", "terminal failure needs a reason")
        return intent

    async def _transition(
        self,
        stored: StoredIntent,
        to_state: str,
        *,
        caller: ActionCaller,
        operation: str,
        now: datetime,
        reason: str | None = None,
        intent_updates: Mapping[str, Any] | None = None,
        envelope_updates: Mapping[str, Any] | None = None,
        verified: bool = False,
    ) -> StoredIntent:
        from_state = stored.state
        assert_transition(from_state, to_state)
        etag = self._etag(stored)
        created = parse_timestamp(stored.intent.created_at.root)
        wire = intent_to_wire(stored.intent)
        wire.update(intent_updates or {})
        wire["state"] = to_state
        wire["status_reason"] = reason
        wire["state_changed_at"] = format_timestamp(max(now, created))
        intent = self._validate_intent(wire)
        updated = stored.model_copy(
            update={
                "intent": intent,
                "due_at": self._due_at(intent, now),
                **(envelope_updates or {}),
            }
        )
        transition = {"from_state": from_state, "to_state": to_state, "reason": reason}
        await self._auditor.record(
            self._event(
                stored,
                caller,
                operation,
                "before",
                state_digest=intent_digest(stored.intent),
                **transition,
            )
        )
        try:
            saved = await self._store.replace(updated, if_match=etag)
        except NeuroSphereError as exc:
            await self._record_write_failure(stored, caller, operation, transition, exc)
            raise
        await self._auditor.record(
            self._event(
                saved,
                caller,
                operation,
                "after",
                state_digest=intent_digest(saved.intent),
                result=_result_for(to_state),
                verified=verified,
                **transition,
            )
        )
        return saved

    async def _record_write_failure(
        self,
        stored: StoredIntent,
        caller: ActionCaller,
        operation: str,
        transition: Mapping[str, Any],
        exc: NeuroSphereError,
    ) -> None:
        """Best effort: the store refused the write; the original error is what the caller sees."""
        try:
            await self._auditor.record(
                self._event(
                    stored,
                    caller,
                    operation,
                    "after",
                    result="failed",
                    state_digest=intent_digest(stored.intent),
                    **{**transition, "reason": _reason_of(exc)},
                )
            )
        except Exception:  # noqa: S110 - the store error below is the one to surface
            pass
