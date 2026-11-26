"""Policy exceptions through HITL (PRP-105 item 3, acceptance criterion 4; clarifications 7, 8).

Request (:class:`ExceptionRequester`):

* the requester needs ``action.propose`` in the violation's domain, checked against the
  SERVER-DERIVED scope through an injected permission check (core ``permits`` by default; no API
  code is imported). A domain outside the scope is ``not_found`` (the same answer as a missing
  violation); a visible domain without the permission is ``forbidden``;
* the violation must be ``open``; the justification is a reason code plus bounded text, and the
  expiry is in the future and at most ``max_days`` (``NS_GOVPOLICY_EXCEPTION_MAX_DAYS``, default
  90, never above the contract's 365) after the request;
* the exception id and the HITL item id are derived from the violation id and a request ordinal
  (exceptions of the violation already closed + 1), so a retried request derives the same ids and
  ends in ``stale_version`` ``review_item_exists`` instead of a second review;
* a ``policy_exception`` HITL item is opened with ``subject_ref`` = the violation's canonical id
  and the requester as maker, so the shipped self-approval rule refuses the requester as
  reviewer (``self_approval_forbidden``); reviewers need ``catalog.curate`` (``hitl/policy.py``);
* audited as ``govpolicy.exception_request`` on the customer's governance-policy chain.

The justification TEXT has no field in PRP-99 ``PolicyException`` (only ``reason_code``) and HITL
items carry no free text, so it is validated and bounded here and only its SHA-256 digest is
kept (in the audit subject's state digest); nothing else stores it.

Read-back (:class:`ExceptionReconciler`, clarification 8): the evaluator reads each requested
exception's HITL item every tick (HITL code is not edited). ``approved`` -> the exception becomes
``approved`` and, until ``expires_at``, the violation is ``excepted`` (that is what "active"
means: approved and unexpired); ``rejected`` or an expired review -> the exception closes and the
violation stays ``open``; an approved exception past its expiry -> ``expired`` and the violation
returns to ``open``. Each decision is audited ``govpolicy.exception_decide`` and sent to the
:class:`~.events.ViolationEventSink`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast

from neurosphere_contracts.audit.v1.audit_record import Subject

from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    build_before,
    build_denied,
    run_audited_mutation,
)
from neurosphere_core.audit.builders import Channel, DenialCode, make_subject
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.auth.scope.permissions import Permission, permits
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    ValidationIssue,
)
from neurosphere_core.governance.policy.events import (
    ExceptionDecidedEvent,
    NoopViolationEventSink,
    ViolationEventSink,
)
from neurosphere_core.governance.policy.ids import (
    POLICY_EXCEPTION_ENTITY_TYPE,
    POLICY_VIOLATION_ENTITY_TYPE,
    exception_canonical_id,
    governance_policy_chain_id,
    violation_canonical_id,
)
from neurosphere_core.governance.policy.models import PolicyException
from neurosphere_core.governance.policy.store import (
    EXCEPTION_EXISTS,
    VIOLATION_NOT_FOUND,
    ExceptionFilters,
    ExceptionStore,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    StoredException,
    ViolationStore,
)
from neurosphere_core.hitl import HitlService, ImmutableDecision, ReviewItem
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

__all__ = [
    "CONTRACT_MAX_EXCEPTION_DAYS",
    "DEFAULT_EXCEPTION_MAX_DAYS",
    "EXCEPTION_REQUEST_FORBIDDEN",
    "INVALID_EXCEPTION_EXPIRY",
    "INVALID_JUSTIFICATION",
    "MAX_JUSTIFICATION_CHARS",
    "OPERATION_EXCEPTION_DECIDE",
    "OPERATION_EXCEPTION_REQUEST",
    "REQUESTER_UNRESOLVABLE",
    "VIOLATION_NOT_OPEN",
    "ExceptionReconciler",
    "ExceptionRequest",
    "ExceptionRequestResult",
    "ExceptionRequester",
    "ExceptionSyncSummary",
    "PermissionCheck",
    "ReviewerResolver",
    "default_permission_check",
    "default_reviewer_resolver",
    "exception_id_for",
    "review_item_id_for",
]

OPERATION_EXCEPTION_REQUEST: Final = "govpolicy.exception_request"
OPERATION_EXCEPTION_DECIDE: Final = "govpolicy.exception_decide"
#: ``NS_GOVPOLICY_EXCEPTION_MAX_DAYS`` default and the contract ceiling.
DEFAULT_EXCEPTION_MAX_DAYS: Final = 90
CONTRACT_MAX_EXCEPTION_DAYS: Final = 365
MAX_JUSTIFICATION_CHARS: Final = 1000

EXCEPTION_REQUEST_FORBIDDEN: Final = "exception_request_forbidden"
VIOLATION_NOT_OPEN: Final = "violation_not_open"
INVALID_JUSTIFICATION: Final = "invalid_justification"
INVALID_EXCEPTION_EXPIRY: Final = "invalid_exception_expiry"
REQUESTER_UNRESOLVABLE: Final = "requester_unresolvable"

#: Fixed namespace of the deterministic exception and review-item ids (never change).
_NAMESPACE: Final = uuid.UUID("9b2f1c64-7e0d-4a38-b5c1-2d6e8f0a4c17")
_REASON_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PRINCIPAL_ID: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]{1,128}:entra:(person|principal):p-[0-9a-f]{64}$"
)
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CLOSED: Final = frozenset({"rejected", "expired", "revoked"})
_SYNC_PAGE: Final = 100
_SYNC_MAX_PAGES: Final = 20

PermissionCheck = Callable[[IdentityScope, Permission, str, datetime], bool]
"""(server-derived scope, permission, domain id, now) -> allowed."""

ReviewerResolver = Callable[[ReviewItem, ImmutableDecision | None], str | None]
"""The decided review's reviewer as a contract principal id, or None when it cannot be named."""

Clock = Callable[[], datetime]
DecidedStatus = Literal["approved", "rejected", "expired", "revoked"]

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _invalid(reason: str, pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, errors=[ValidationIssue(pointer, detail)], reason=reason)


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None) if isinstance(exc, NeuroSphereError) else None
    return reason if isinstance(reason, str) and reason else "error"


def default_permission_check(
    scope: IdentityScope, permission: Permission, domain_id: str, now: datetime
) -> bool:
    """Core :func:`~neurosphere_core.auth.scope.permissions.permits` on the domain."""
    return permits(scope, permission, now=now, domain_id=domain_id)


def default_reviewer_resolver(item: ReviewItem, decision: ImmutableDecision | None) -> str | None:
    """``<cloud>:<customer>:entra:(person|principal):<pseudonym>`` of the decision's reviewer.

    PRP-06 pseudonyms are ``p-<64 hex>``; anything that does not form a contract principal id
    is ``None`` (the exception then waits, counted ``reviewer_unresolved``).
    """
    if decision is None:
        return None
    reviewer = decision.reviewer
    kind = "person" if reviewer.principal_kind == "user" else "principal"
    candidate = ":".join(
        (item.cloud, item.customer_id, "entra", kind, reviewer.principal_pseudonym)
    )
    return candidate if _PRINCIPAL_ID.fullmatch(candidate) else None


def exception_id_for(violation_id: str, ordinal: int) -> str:
    """Deterministic exception id of the ``ordinal``-th request on a violation (uuid5)."""
    if ordinal < 1:
        raise ValueError("ordinal starts at 1")
    return str(uuid.uuid5(_NAMESPACE, f"policy_exception|{uuid.UUID(violation_id)}|{ordinal}"))


def review_item_id_for(exception_id: str) -> str:
    """Deterministic HITL item id of an exception's review (uuid5)."""
    return str(uuid.uuid5(_NAMESPACE, f"policy_exception_review|{uuid.UUID(exception_id)}"))


def _principal_id(scope: IdentityScope) -> str:
    principal = scope.to_contract().principal.principal_id
    return str(getattr(principal, "root", principal))


# --- request ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExceptionRequest:
    """What the requester asks for. ``domain_id`` + ``violation_id`` name the violation."""

    domain_id: str
    violation_id: str
    justification_code: str
    justification_text: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExceptionRequestResult:
    exception: StoredException
    review_item: ReviewItem


class ExceptionRequester:
    """Opens time-boxed exception requests (see the module docstring)."""

    def __init__(
        self,
        violations: ViolationStore,
        exceptions: ExceptionStore,
        hitl: HitlService,
        audit: AuditRepository,
        *,
        permission_check: PermissionCheck = default_permission_check,
        max_days: int = DEFAULT_EXCEPTION_MAX_DAYS,
        clock: Clock = _utc_now,
    ) -> None:
        if not 1 <= max_days <= CONTRACT_MAX_EXCEPTION_DAYS:
            raise ValueError("max_days must be 1..365")
        self._violations = violations
        self._exceptions = exceptions
        self._hitl = hitl
        self._audit = audit
        self._check = permission_check
        self._max_days = max_days
        self._clock = clock

    @property
    def max_days(self) -> int:
        return self._max_days

    async def request(
        self,
        scope: IdentityScope,
        request: ExceptionRequest,
        *,
        correlation_id: str,
        channel: Channel | None = "rest",
    ) -> ExceptionRequestResult:
        now = self._clock()
        customer = scope.customer_id
        if request.domain_id not in scope.allowed_domains:
            raise GovernancePolicyNotFoundError(VIOLATION_NOT_FOUND)
        stored = await self._violations.get(customer, request.domain_id, request.violation_id)
        if stored is None:
            raise GovernancePolicyNotFoundError(VIOLATION_NOT_FOUND)
        violation = stored.violation
        canonical = violation_canonical_id(
            violation.cloud.root, customer, violation.violation_id.root
        )
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=correlation_id,
            operation=OPERATION_EXCEPTION_REQUEST,
            channel=channel,
        )
        chain = governance_policy_chain_id(customer)
        try:
            self._validate(scope, request, now, violation.status)
        except (ForbiddenError, InvalidSchemaError, GovernancePolicyStaleError) as exc:
            await self._audit.append(
                chain,
                build_denied(
                    ctx,
                    code=cast(DenialCode, exc.code),
                    reason=_reason(exc),
                    subject=make_subject(canonical, POLICY_VIOLATION_ENTITY_TYPE),
                ),
            )
            raise
        ordinal = await self._ordinal(customer, request)
        exception_id = exception_id_for(violation.violation_id.root, ordinal)
        item_id = review_item_id_for(exception_id)
        requester = _principal_id(scope)
        exception = PolicyException.model_validate(
            {
                "schema_version": "1.2.0",
                "exception_id": exception_id,
                "cloud": violation.cloud.root,
                "customer_id": customer,
                "domain_id": request.domain_id,
                "policy_id": violation.policy_id.root,
                "rule_id": violation.rule_id.root,
                "subject": violation.subject.model_dump(mode="json"),
                "violation_id": violation.violation_id.root,
                "status": "requested",
                "reason_code": request.justification_code,
                "requested_by": requester,
                "requested_at": _timestamp(now),
                "review_item_id": item_id,
                "expires_at": _timestamp(request.expires_at),
            }
        )
        subject = make_subject(
            canonical,
            POLICY_VIOLATION_ENTITY_TYPE,
            state={
                "exception_id": exception_id,
                "justification_code": request.justification_code,
                "justification_sha256": sha256_digest(request.justification_text),
                "expires_at": _timestamp(request.expires_at),
            },
        )

        async def mutate() -> ExceptionRequestResult:
            try:
                made = await self._exceptions.request(exception)
            except GovernancePolicyStaleError as exc:
                if exc.reason != EXCEPTION_EXISTS:
                    raise
                existing = await self._exceptions.get(customer, request.domain_id, exception_id)
                if existing is None:
                    raise
                made = existing  # a retry: opening the review below reports review_item_exists
            item = await self._hitl.open_item(
                kind="policy_exception",
                customer_id=customer,
                domain_id=request.domain_id,
                subject_ref=canonical,
                now=now,
                correlation_id=correlation_id,
                item_id=item_id,
                maker_principal_id=requester,
                maker=ctx.actor,
                opened_by=ctx.actor,
                scope_hash=scope.scope_hash,
                channel=channel,
            )
            return ExceptionRequestResult(exception=made, review_item=item)

        return await run_audited_mutation(
            self._audit,
            chain,
            before=build_before(ctx, subject),
            mutate=mutate,
            after=lambda _: build_after(
                ctx, subject, result="succeeded", verified=True, detail="exception_requested"
            ),
            on_error=lambda exc: build_after(
                ctx, subject, result="failed", verified=False, detail=_reason(exc)
            ),
        )

    def _validate(
        self, scope: IdentityScope, request: ExceptionRequest, now: datetime, status: str
    ) -> None:
        if not self._check(scope, Permission.ACTION_PROPOSE, request.domain_id, now):
            raise ForbiddenError(
                "requesting an exception needs action.propose in the violation's domain",
                reason=EXCEPTION_REQUEST_FORBIDDEN,
            )
        if not _PRINCIPAL_ID.fullmatch(_principal_id(scope)):
            raise _invalid(REQUESTER_UNRESOLVABLE, "/requested_by", "not a pseudonymous principal")
        if status != "open":
            raise GovernancePolicyStaleError(VIOLATION_NOT_OPEN, "the violation is not open")
        if not _REASON_CODE.fullmatch(request.justification_code):
            raise _invalid(INVALID_JUSTIFICATION, "/justification_code", "not a reason code")
        text = request.justification_text
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_JUSTIFICATION_CHARS
            or _CONTROL.search(text) is not None
        ):
            raise _invalid(
                INVALID_JUSTIFICATION,
                "/justification_text",
                f"1 to {MAX_JUSTIFICATION_CHARS} characters, no control characters",
            )
        expires = request.expires_at
        if expires.tzinfo is None:
            raise _invalid(INVALID_EXCEPTION_EXPIRY, "/expires_at", "must be timezone-aware")
        if expires <= now or expires > now + timedelta(days=self._max_days):
            raise _invalid(
                INVALID_EXCEPTION_EXPIRY,
                "/expires_at",
                f"must be after now and at most {self._max_days} days ahead",
            )

    async def _ordinal(self, customer_id: str, request: ExceptionRequest) -> int:
        """Closed exceptions of the violation + 1 (an open one keeps the same ordinal)."""
        closed = 0
        cursor: str | None = None
        for _ in range(_SYNC_MAX_PAGES):
            page = await self._exceptions.list(
                customer_id,
                ExceptionFilters(
                    domain_ids=(request.domain_id,), violation_id=request.violation_id
                ),
                PageRequest(page_size=_SYNC_PAGE, cursor=cursor),
            )
            closed += sum(1 for s in page.items if s.exception.status in _CLOSED)
            cursor = page.next_cursor
            if cursor is None:
                break
        return closed + 1


# --- read-back ----------------------------------------------------------------------------------


@dataclass(slots=True)
class ExceptionSyncSummary:
    """Counts of one read-back pass (ids and counts only)."""

    checked: int = 0
    approved: int = 0
    rejected: int = 0
    expired: int = 0
    violations_excepted: int = 0
    violations_reopened: int = 0
    reviewer_unresolved: int = 0
    failed: int = 0
    truncated: bool = False
    decided_ids: list[str] = field(default_factory=list)


class ExceptionReconciler:
    """Moves exceptions along their HITL review each evaluation tick (clarification 8)."""

    def __init__(
        self,
        exceptions: ExceptionStore,
        violations: ViolationStore,
        hitl: HitlService,
        audit: AuditRepository,
        *,
        events: ViolationEventSink | None = None,
        reviewer_resolver: ReviewerResolver = default_reviewer_resolver,
    ) -> None:
        self._exceptions = exceptions
        self._violations = violations
        self._hitl = hitl
        self._audit = audit
        self._events = events or NoopViolationEventSink()
        self._resolve = reviewer_resolver

    async def sync(
        self,
        scope: IdentityScope,
        domain_ids: tuple[str, ...],
        *,
        now: datetime,
        correlation_id: str,
    ) -> ExceptionSyncSummary:
        """One pass over ``requested`` and ``approved`` exceptions in ``domain_ids``."""
        summary = ExceptionSyncSummary()
        if not domain_ids:
            return summary
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=correlation_id,
            operation=OPERATION_EXCEPTION_DECIDE,
            channel="worker",
        )
        for status in ("requested", "approved"):
            cursor: str | None = None
            for page_number in range(_SYNC_MAX_PAGES):
                page = await self._exceptions.list(
                    scope.customer_id,
                    ExceptionFilters(domain_ids=domain_ids, status=status),
                    PageRequest(page_size=_SYNC_PAGE, cursor=cursor),
                )
                for stored in page.items:
                    summary.checked += 1
                    try:
                        await self._one(ctx, stored, now, summary)
                    except Exception as exc:
                        summary.failed += 1
                        _log.warning(
                            "govpolicy_exception_sync_failed exception_id=%s reason=%s",
                            stored.exception.exception_id.root,
                            _reason(exc),
                        )
                cursor = page.next_cursor
                if cursor is None:
                    break
                if page_number + 1 == _SYNC_MAX_PAGES:
                    summary.truncated = True
        return summary

    async def _one(
        self,
        ctx: AuditContext,
        stored: StoredException,
        now: datetime,
        summary: ExceptionSyncSummary,
    ) -> None:
        exception = stored.exception
        expired = _parse(exception.expires_at.root) <= now
        if exception.status == "approved":
            if expired:
                closed = await self._decide(ctx, stored, "expired", None, now)
                summary.expired += 1
                summary.decided_ids.append(exception.exception_id.root)
                if await self._set_violation(closed.exception, None):
                    summary.violations_reopened += 1
            elif await self._set_violation(exception, exception.exception_id.root):
                summary.violations_excepted += 1
            return
        item_id = exception.review_item_id.root if exception.review_item_id is not None else None
        item = None if item_id is None else await self._hitl.get(item_id)
        if item is None:
            return
        state = item.state_name
        if state == "expired":
            await self._decide(ctx, stored, "expired", None, now)
            summary.expired += 1
            summary.decided_ids.append(exception.exception_id.root)
            return
        if state not in ("approved", "rejected"):
            return  # still under review
        decision = await self._decision(item)
        reviewer = self._resolve(item, decision)
        if reviewer is None:
            summary.reviewer_unresolved += 1
            return
        decided_at = item.decided_at or now
        target: Literal["approved", "rejected"] = "approved" if state == "approved" else "rejected"
        decided = await self._decide(ctx, stored, target, (reviewer, decided_at), now)
        summary.decided_ids.append(exception.exception_id.root)
        if target == "rejected":
            summary.rejected += 1
            return
        summary.approved += 1
        if expired:
            closed = await self._decide(ctx, decided, "expired", None, now)
            summary.expired += 1
            if await self._set_violation(closed.exception, None):
                summary.violations_reopened += 1
        elif await self._set_violation(decided.exception, exception.exception_id.root):
            summary.violations_excepted += 1

    async def _decision(self, item: ReviewItem) -> ImmutableDecision | None:
        if item.decision_id is None:
            return None
        for decision in await self._hitl.decisions(item.item_id):
            if str(decision.decision_id.root) == item.decision_id:
                return decision
        return None

    async def _decide(
        self,
        ctx: AuditContext,
        stored: StoredException,
        status: Literal["approved", "rejected", "expired"],
        decision: tuple[str, datetime] | None,
        now: datetime,
    ) -> StoredException:
        exception = stored.exception
        chain = governance_policy_chain_id(exception.customer_id.root)
        subject = self._subject(exception, status)
        before = await self._audit.append(chain, build_before(ctx, subject))
        try:
            changed = await self._exceptions.set_state(
                exception.customer_id.root,
                exception.domain_id.root,
                exception.exception_id.root,
                status,
                if_match=stored.etag,
                decided_by=decision[0] if decision is not None else None,
                decided_at=decision[1] if decision is not None else None,
                audit_id=str(before.audit_id.root),
            )
        except Exception as exc:
            await self._audit.append(
                chain,
                build_after(ctx, subject, result="failed", verified=False, detail=_reason(exc)),
            )
            raise
        await self._audit.append(
            chain,
            build_after(
                ctx, subject, result="succeeded", verified=True, detail=f"exception_{status}"
            ),
        )
        await self._emit(changed.exception, status, ctx.correlation_id)
        return changed

    async def _set_violation(self, exception: PolicyException, exception_id: str | None) -> bool:
        """Mark the violation excepted under ``exception_id`` (or back to open with ``None``).

        True when the violation changed. A violation that is resolved, gone, or already in the
        wanted state is left alone.
        """
        if exception.violation_id is None:
            return False
        current = await self._violations.get(
            exception.customer_id.root, exception.domain_id.root, exception.violation_id.root
        )
        if current is None or current.violation.status not in ("open", "excepted"):
            return False
        held = current.violation.exception_id
        held_id = held.root if held is not None else None
        if exception_id is None:
            if held_id != exception.exception_id.root:
                return False  # excepted under another exception (or already open)
        elif held_id == exception_id:
            return False
        await self._violations.set_exception(
            exception.customer_id.root,
            exception.domain_id.root,
            exception.violation_id.root,
            exception_id,
            if_match=current.etag,
        )
        return True

    async def _emit(self, exception: PolicyException, status: str, correlation_id: str) -> None:
        event = ExceptionDecidedEvent(
            cloud=exception.cloud.root,
            customer_id=exception.customer_id.root,
            domain_id=exception.domain_id.root,
            exception_id=exception.exception_id.root,
            violation_id=(
                exception.violation_id.root if exception.violation_id is not None else None
            ),
            policy_id=exception.policy_id.root,
            rule_id=exception.rule_id.root,
            subject_id=exception.subject.canonical_id,
            status=cast(DecidedStatus, status),
            correlation_id=correlation_id,
        )
        try:
            await self._events.exception_decided(event)
        except Exception as exc:
            _log.warning("govpolicy_event_sink_failed reason=%s", type(exc).__name__)

    @staticmethod
    def _subject(exception: PolicyException, status: str) -> Subject:
        return make_subject(
            exception_canonical_id(
                exception.cloud.root, exception.customer_id.root, exception.exception_id.root
            ),
            POLICY_EXCEPTION_ENTITY_TYPE,
            state={"status": status, "exception_id": exception.exception_id.root},
        )
