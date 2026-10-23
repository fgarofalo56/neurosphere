"""Lifecycle engine: evaluates the conflict rules, executes, verifies by read-back, audits.

Order of evaluation follows ``rules.py``. Nothing is forced: a blocked request is queued and
audited and re-evaluated by :meth:`LifecycleEngine.process_queue`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from neurosphere_contracts.audit.v1.audit_record import Subject

from neurosphere_core.audit.builders import (
    AuditContext,
    AuditDraft,
    build_after,
    build_allowed,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.audit.repository import AuditRepository, run_audited_mutation
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle.holds import matching_holds
from neurosphere_core.lifecycle.models import (
    ActionKind,
    Effect,
    ExportItem,
    ExportRequest,
    ExportResult,
    JobStatus,
    LegalHold,
    LifecycleOutcome,
    LifecycleRequest,
    Rule,
    TargetRecord,
    TargetRef,
)
from neurosphere_core.lifecycle.policy import UNSET, PolicyState
from neurosphere_core.lifecycle.rules import is_audit_container, is_audit_label, is_audit_record
from neurosphere_core.lifecycle.targets import (
    HoldRegistry,
    LifecycleTarget,
    PseudonymMappingStore,
    QueuedRequest,
    RequestQueue,
    TargetRegistry,
)
from neurosphere_core.scope import IdentityScope

Clock = Callable[[], datetime]
Cloud = Literal["commercial", "government"]
_SLUG: Final = re.compile(r"[^a-z0-9._-]+")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _ReadBackFailedError(Exception):
    """Internal: the target still shows the change as not done after the action."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _slug(value: str) -> str:
    return _SLUG.sub("-", value.lower()).strip("-") or "x"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class LifecycleEngine:
    def __init__(
        self,
        *,
        policy: PolicyState = UNSET,
        targets: TargetRegistry,
        holds: HoldRegistry,
        queue: RequestQueue,
        audit: AuditRepository,
        audit_chain_id: str,
        cloud: Cloud,
        customer_id: str,
        mappings: PseudonymMappingStore | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._policy = policy
        self._targets = targets
        self._holds = holds
        self._queue = queue
        self._audit = audit
        self._chain = audit_chain_id
        self._cloud: Cloud = cloud
        self._customer = _slug(customer_id)
        self._mappings = mappings
        self._clock = clock

    # -- policy ------------------------------------------------------------------------------

    @property
    def policy(self) -> PolicyState:
        return self._policy

    def set_policy(self, policy: PolicyState) -> None:
        self._policy = policy

    @property
    def bodies_retained(self) -> bool:
        return self._policy.bodies_retained

    # -- audit helpers -----------------------------------------------------------------------

    def _ctx(self, ctx: AuditContext, operation: str) -> AuditContext:
        return ctx.model_copy(update={"operation": operation})

    def _canonical(self, entity: str, ident: str, container: str = "-") -> str:
        return (
            f"{self._cloud}:{self._customer}:lifecycle:{_slug(entity)}:"
            f"{_slug(container)}/{_digest(ident)}"
        )

    def _subject(
        self, request: LifecycleRequest, record: TargetRecord | None, *, after: bool
    ) -> Subject:
        if request.target is None:
            return make_subject(
                self._canonical("pseudonym_mapping", request.subject_id or ""),
                "pseudonym_mapping",
                state_digest=None,
            )
        ref = request.target
        digest = None
        if record is not None and not after:
            digest = sha256_digest(
                {"data_class": record.data_class, "pseudonymized": record.pseudonymized}
            )
        return make_subject(
            self._canonical(ref.target_kind, ref.record_id, ref.container),
            "lifecycle_target",
            state_digest=digest,
        )

    async def _denied(
        self, ctx: AuditContext, request: LifecycleRequest, record: TargetRecord | None, reason: str
    ) -> None:
        op = f"lifecycle.{request.action.value}"
        await self._audit.append(
            self._chain,
            build_denied(
                self._ctx(ctx, op),
                code="forbidden",
                reason=reason,
                subject=self._subject(request, record, after=False),
            ),
        )

    def _outcome(
        self,
        request: LifecycleRequest,
        status: JobStatus,
        reason: str,
        **extra: object,
    ) -> LifecycleOutcome:
        return LifecycleOutcome.model_validate(
            {
                "request_id": request.request_id,
                "action": request.action,
                "status": status,
                "reason": reason,
                "policy_status": self._policy.status,
                **extra,
            }
        )

    # -- submit / evaluate -------------------------------------------------------------------

    async def submit(self, request: LifecycleRequest, ctx: AuditContext) -> LifecycleOutcome:
        return await self._decide(request, ctx, initial=True)

    async def _defer(
        self,
        request: LifecycleRequest,
        ctx: AuditContext,
        record: TargetRecord | None,
        *,
        rule: Rule | None,
        reason: str,
        initial: bool,
        not_before: datetime | None = None,
    ) -> LifecycleOutcome:
        item = QueuedRequest(
            request=request,
            ctx=ctx,
            blocked_by=rule,
            reason=reason,
            queued_at=self._clock(),
            not_before=not_before,
        )
        if initial and await self._queue.enqueue(item):
            await self._denied(ctx, request, record, reason)
        return self._outcome(
            request,
            JobStatus.QUEUED,
            reason,
            blocked_by=rule,
            governing_rule=rule,
            not_before=not_before,
        )

    async def _decide(
        self, request: LifecycleRequest, ctx: AuditContext, *, initial: bool
    ) -> LifecycleOutcome:
        ref = request.target
        target: LifecycleTarget | None = None
        record: TargetRecord | None = None
        # Rule 1: audit immutability. Identity from labels AND from what the store holds.
        if ref is not None:
            if is_audit_label(ref):
                return await self._refuse(request, ctx, None, "audit_immutable")
            target = self._targets.get(ref.target_kind, ref.container)
            if target is None:
                return await self._refuse(request, ctx, None, "unknown_target")
            if is_audit_container(target.container):
                return await self._refuse(request, ctx, None, "audit_immutable")
            record = await target.get(ref.record_id)
            if is_audit_record(record):
                return await self._refuse(request, ctx, record, "audit_immutable")
            if record is None:
                return self._outcome(request, JobStatus.NOT_DUE, "target_absent")
        # Rule 2: legal hold.
        holds = await self._holds.active()
        if matching_holds(holds, ref=ref, record=record, subject_id=request.subject_id):
            return await self._defer(
                request, ctx, record, rule=Rule.LEGAL_HOLD, reason="legal_hold", initial=initial
            )
        # Missing policy fails closed.
        policy = self._policy.policy
        if policy is None:
            return await self._defer(
                request, ctx, record, rule=None, reason="policy_unset", initial=initial
            )
        now = self._clock()
        if request.action is ActionKind.ERASE_SUBJECT:
            return await self._execute_erase(request, ctx)
        assert record is not None and target is not None and ref is not None
        rule = policy.rule_for(record.data_class)
        if rule is None:
            return await self._defer(
                request, ctx, record, rule=None, reason="no_rule_for_data_class", initial=initial
            )
        # Rule 3: minimum retention.
        earliest = record.created_at + timedelta(days=rule.min_retention_days)
        if now < earliest:
            return await self._defer(
                request,
                ctx,
                record,
                rule=Rule.MIN_RETENTION,
                reason="min_retention",
                initial=initial,
                not_before=earliest,
            )
        if request.action is ActionKind.EXPIRE:
            # Rule 5: maximum retention expiry.
            if now < record.created_at + timedelta(days=rule.max_retention_days):
                return self._outcome(request, JobStatus.NOT_DUE, "not_expired")
            return await self._execute_delete(
                request, ctx, target, ref, record, Rule.MAX_RETENTION_EXPIRY
            )
        # Rule 4: subject request.
        if request.action is ActionKind.PSEUDONYMIZE:
            return await self._execute_pseudonymize(request, ctx, target, ref, record)
        return await self._execute_delete(request, ctx, target, ref, record, Rule.SUBJECT_REQUEST)

    async def _refuse(
        self, request: LifecycleRequest, ctx: AuditContext, record: TargetRecord | None, reason: str
    ) -> LifecycleOutcome:
        await self._denied(ctx, request, record, reason)
        rule = Rule.AUDIT_IMMUTABILITY if reason == "audit_immutable" else None
        return self._outcome(
            request, JobStatus.REFUSED, reason, governing_rule=rule, blocked_by=rule
        )

    # -- execution ---------------------------------------------------------------------------

    async def _run(
        self,
        request: LifecycleRequest,
        ctx: AuditContext,
        record: TargetRecord | None,
        mutate: Callable[[], Awaitable[None]],
        success_detail: str,
        *,
        governing: Rule,
    ) -> tuple[bool, str]:
        """Before record, mutate (which reads back), after record. Returns (ok, detail)."""
        op = self._ctx(ctx, f"lifecycle.{request.action.value}")
        before_subject = self._subject(request, record, after=False)
        after_subject = self._subject(request, record, after=True)

        async def go() -> str:
            await mutate()
            return success_detail

        def failed(exc: BaseException) -> AuditDraft:
            code = exc.code if isinstance(exc, _ReadBackFailedError) else "action_error"
            return build_after(op, after_subject, result="failed", verified=False, detail=code)

        try:
            detail = await run_audited_mutation(
                self._audit,
                self._chain,
                before=build_before(op, before_subject),
                mutate=go,
                after=lambda d: build_after(
                    op, after_subject, result="succeeded", verified=True, detail=d
                ),
                on_error=failed,
            )
        except _ReadBackFailedError as exc:
            return False, exc.code
        except CapabilityUnavailableError as exc:
            return False, exc.reason or "capability_unavailable"
        del governing
        return True, detail

    async def _execute_delete(
        self,
        request: LifecycleRequest,
        ctx: AuditContext,
        target: LifecycleTarget,
        ref: TargetRef,
        record: TargetRecord,
        governing: Rule,
    ) -> LifecycleOutcome:
        async def mutate() -> None:
            await target.delete(ref.record_id)
            if await target.get(ref.record_id) is not None:
                raise _ReadBackFailedError("readback_found_target")

        ok, detail = await self._run(request, ctx, record, mutate, "deleted", governing=governing)
        if not ok:
            return self._outcome(request, JobStatus.FAILED, detail, governing_rule=governing)
        return self._outcome(
            request,
            JobStatus.COMPLETED,
            "deleted",
            governing_rule=governing,
            effect=Effect.DELETED,
            verified=True,
        )

    async def _execute_pseudonymize(
        self,
        request: LifecycleRequest,
        ctx: AuditContext,
        target: LifecycleTarget,
        ref: TargetRef,
        record: TargetRecord,
    ) -> LifecycleOutcome:
        original = record.subject_id

        async def mutate() -> None:
            await target.pseudonymize(ref.record_id)
            after = await target.get(ref.record_id)
            if (
                after is None
                or not after.pseudonymized
                or (original is not None and after.subject_id == original)
            ):
                raise _ReadBackFailedError("readback_not_pseudonymized")

        ok, detail = await self._run(
            request, ctx, record, mutate, "pseudonymized", governing=Rule.SUBJECT_REQUEST
        )
        if not ok:
            return self._outcome(
                request, JobStatus.FAILED, detail, governing_rule=Rule.SUBJECT_REQUEST
            )
        reidentifiable: bool | None = None
        if self._mappings is not None and original is not None:
            reidentifiable = await self._mappings.exists(original)
        return self._outcome(
            request,
            JobStatus.COMPLETED,
            "pseudonymized",
            governing_rule=Rule.SUBJECT_REQUEST,
            effect=Effect.PSEUDONYMIZED,
            verified=True,
            reidentifiable=reidentifiable,
        )

    async def _execute_erase(
        self, request: LifecycleRequest, ctx: AuditContext
    ) -> LifecycleOutcome:
        subject = request.subject_id or ""
        mappings = self._mappings
        if mappings is None:
            return await self._refuse(request, ctx, None, "mapping_store_unavailable")

        async def mutate() -> None:
            await mappings.destroy(subject)
            if await mappings.exists(subject):
                raise _ReadBackFailedError("readback_found_mapping")

        ok, detail = await self._run(
            request, ctx, None, mutate, "mapping_destroyed", governing=Rule.SUBJECT_REQUEST
        )
        if not ok:
            return self._outcome(
                request, JobStatus.FAILED, detail, governing_rule=Rule.SUBJECT_REQUEST
            )
        return self._outcome(
            request,
            JobStatus.COMPLETED,
            "mapping_destroyed",
            governing_rule=Rule.SUBJECT_REQUEST,
            effect=Effect.MAPPING_DESTROYED,
            verified=True,
            reidentifiable=False,
        )

    # -- sweeps ------------------------------------------------------------------------------

    async def process_queue(self) -> list[LifecycleOutcome]:
        """Re-evaluate queued requests; those whose blocking rule lifted run and leave the queue."""
        results: list[LifecycleOutcome] = []
        for item in await self._queue.pending():
            outcome = await self._decide(item.request, item.ctx, initial=False)
            if outcome.status is not JobStatus.QUEUED:
                await self._queue.remove(item.request.request_id)
                results.append(outcome)
        return results

    async def sweep_expiry(
        self, ctx: AuditContext, *, target: LifecycleTarget, data_class: str, limit: int = 100
    ) -> list[LifecycleOutcome]:
        """Submit EXPIRE for one bounded page of a class. Under no policy this deletes nothing."""
        if self._policy.policy is None:
            return []
        out: list[LifecycleOutcome] = []
        for rec in await target.list_records(data_class=data_class, limit=limit, after=None):
            req = LifecycleRequest(
                action=ActionKind.EXPIRE,
                target=TargetRef(
                    target_kind=target.target_kind,
                    container=target.container,
                    record_id=rec.record_id,
                ),
            )
            out.append(await self.submit(req, ctx))
        return out

    # -- export ------------------------------------------------------------------------------

    async def export(
        self, request: ExportRequest, scope: IdentityScope, ctx: AuditContext
    ) -> ExportResult:
        """Scope-filtered, lawful-basis export. Scope comes from ``scope``, never the request."""
        op = self._ctx(ctx, f"lifecycle.export.{request.lawful_basis.value}")
        probe = TargetRef(
            target_kind=request.target_kind, container=request.container, record_id="-"
        )
        container_subject = make_subject(
            self._canonical(request.target_kind, request.container, request.container),
            "lifecycle_target",
            state_digest=None,
        )
        if is_audit_label(probe) or is_audit_container(request.container):
            await self._audit.append(
                self._chain,
                build_denied(
                    op, code="forbidden", reason="audit_immutable", subject=container_subject
                ),
            )
            return ExportResult(status=JobStatus.REFUSED, reason="audit_immutable")
        target = self._targets.get(request.target_kind, request.container)
        if target is None:
            await self._audit.append(
                self._chain,
                build_denied(
                    op, code="forbidden", reason="unknown_target", subject=container_subject
                ),
            )
            return ExportResult(status=JobStatus.REFUSED, reason="unknown_target")
        principal = scope.to_contract().principal.principal_pseudonym
        allowed_domains = set(scope.allowed_domains)
        holds = await self._holds.active()
        items: list[ExportItem] = []
        out_of_scope = 0
        held = 0
        for record_id in request.record_ids:
            ref = TargetRef(
                target_kind=request.target_kind, container=request.container, record_id=record_id
            )
            record = await target.get(record_id)
            if record is None or is_audit_record(record):
                out_of_scope += 1
                continue
            if record.customer_id != scope.customer_id or record.domain_id not in allowed_domains:
                out_of_scope += 1
                continue
            applicable = matching_holds(holds, ref=ref, record=record)
            if applicable and not _custodian_of_all(principal, applicable):
                held += 1
                continue
            items.append(
                ExportItem(
                    record_id=record_id,
                    data_class=record.data_class,
                    content=dict(await target.export(record_id)),
                )
            )
        await self._audit.append(self._chain, build_allowed(op, container_subject))
        if held:
            await self._audit.append(
                self._chain,
                build_denied(op, code="forbidden", reason="legal_hold", subject=container_subject),
            )
        return ExportResult(
            status=JobStatus.COMPLETED,
            reason="exported",
            items=tuple(items),
            withheld_out_of_scope=out_of_scope,
            withheld_held=held,
            effect=Effect.EXPORTED,
        )


def _custodian_of_all(principal: str, holds: list[LegalHold]) -> bool:
    return all(principal in h.custodians for h in holds)
