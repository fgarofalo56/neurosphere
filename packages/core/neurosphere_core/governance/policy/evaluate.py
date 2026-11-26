"""One policy evaluation run (PRP-105 item 3, acceptance criteria 2, 3, 4 and 10).

:meth:`PolicyEvaluator.run` is what the ``policy_eval`` worker role (item 5) calls each tick:

1. ``govpolicy.evaluation_run`` ``before`` audit record (fail closed) and a ``running`` status
   document (``doc_kind: evaluation_status``, filed under the customer-control domain);
2. every PUBLISHED policy (highest published version per policy) whose domain the caller's
   SERVER-DERIVED scope covers. A domain policy outside the scope is skipped and listed in
   ``domains_skipped``; a customer-wide policy (the customer-control domain) applies to subjects
   in the domains the scope can see, never wider. A policy in ``mode: off`` is not evaluated;
3. for each rule, a FRESH :class:`~.rules.base.RunBudget` (subject budget + deadline per
   (policy, rule)) and the evaluator from the registry; a kind with no evaluator is recorded
   ``evaluator_unavailable`` with the registry's reason (criterion 10);
4. each finding -> :meth:`~.store.ViolationStore.upsert_observed` (one record per dedup key:
   ids, evidence references and category names, never content); a new record is audited
   ``govpolicy.violation_open`` and sent to the :class:`~.events.ViolationEventSink`;
5. ONLY for a rule whose evaluation finished without truncation or failure,
   :meth:`~.store.ViolationStore.resolve_missing_report` resolves the rule's active violations
   the run did not see (``govpolicy.violation_resolve``). A truncated rule resolves nothing and
   the run says ``truncated`` (criterion 3); a resolve pass that hit its own cap also makes the
   rule ``truncated``;
6. the read-back of requested and approved exceptions (clarification 8,
   :class:`~.exceptions.ExceptionReconciler`) and, when a lifecycle is given, the retry of any
   binding or catalog projection write that failed at publish (:meth:`PolicyLifecycle.reconcile`);
7. the final status (``completed``, ``truncated`` or ``failed``) and the ``after`` audit record.

A failing rule never stops the run (it is ``failed`` and resolves nothing); a store outage before
any rule ran ends the run ``failed`` and re-raises so the worker logs it and waits for the next
tick.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal, cast

from neurosphere_contracts.audit.v1.audit_record import Subject

from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    build_before,
)
from neurosphere_core.audit.builders import make_subject
from neurosphere_core.auth.scope.permissions import customer_control_domain_id
from neurosphere_core.errors import ForbiddenError, NeuroSphereError
from neurosphere_core.governance.policy.events import (
    VIOLATION_OPENED,
    VIOLATION_RESOLVED,
    NoopViolationEventSink,
    ViolationEvent,
    ViolationEventSink,
)
from neurosphere_core.governance.policy.exceptions import (
    ExceptionReconciler,
    ExceptionSyncSummary,
)
from neurosphere_core.governance.policy.ids import (
    NEUROSPHERE_SOURCE,
    POLICY_VIOLATION_ENTITY_TYPE,
    dedup_key,
    governance_policy_chain_id,
    violation_canonical_id,
)
from neurosphere_core.governance.policy.lifecycle import PolicyLifecycle, ReconcileOutcome
from neurosphere_core.governance.policy.models import (
    MAX_RULE_STATUSES,
    MAX_SKIPPED_DOMAINS,
    EvaluationRunState,
    EvaluationStatus,
    EvaluationTrigger,
    PolicyDefinition,
    PolicyRule,
    PolicyViolation,
    RuleKindName,
    RuleOutcomeName,
    RuleRunStatus,
    TargetRef,
)
from neurosphere_core.governance.policy.rules.base import (
    RuleContext,
    RuleEvaluationError,
    RuleFinding,
    RuleOutcome,
    RunBudget,
)
from neurosphere_core.governance.policy.rules.registry import RuleEvaluatorRegistry
from neurosphere_core.governance.policy.store import (
    MAX_DOMAIN_FILTER,
    EvaluationStatusStore,
    PolicyDefinitionStore,
    StoredViolation,
    ViolationObservation,
    ViolationStore,
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DOMAIN_OUT_OF_SCOPE",
    "EVALUATION_RUN_ENTITY_TYPE",
    "EVALUATOR_FAILED",
    "OPERATION_EVALUATION_RUN",
    "OPERATION_VIOLATION_OPEN",
    "OPERATION_VIOLATION_RESOLVE",
    "POLICY_MODE_OFF",
    "RESOLVE_TRUNCATED",
    "RUN_TIME_BUDGET",
    "VIOLATION_WRITE_FAILED",
    "EvaluationBudget",
    "EvaluationRun",
    "PolicyEvaluator",
]

OPERATION_EVALUATION_RUN: Final = "govpolicy.evaluation_run"
OPERATION_VIOLATION_OPEN: Final = "govpolicy.violation_open"
OPERATION_VIOLATION_RESOLVE: Final = "govpolicy.violation_resolve"
EVALUATION_RUN_ENTITY_TYPE: Final = "evaluation_run"

DOMAIN_OUT_OF_SCOPE: Final = "domain_out_of_scope"
POLICY_MODE_OFF: Final = "policy_mode_off"
RUN_TIME_BUDGET: Final = "run_time_budget"
RESOLVE_TRUNCATED: Final = "resolve_truncated"
EVALUATOR_FAILED: Final = "evaluator_failed"
VIOLATION_WRITE_FAILED: Final = "violation_write_failed"
_STORE_UNAVAILABLE: Final = "policy_store_unavailable"
_REASON_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid4() -> str:
    return str(uuid.uuid4())


def _monotonic() -> Callable[[], float]:
    return time.monotonic


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reason_text(reason: object, default: str = EVALUATOR_FAILED) -> str:
    """``reason`` when it is a snake_case reason code, else ``default`` (never free text)."""
    return reason if isinstance(reason, str) and _REASON_CODE.fullmatch(reason) else default


def _reason(exc: BaseException, default: str) -> str:
    reason = getattr(exc, "reason", None) if isinstance(exc, NeuroSphereError) else None
    return _reason_text(reason, default)


def _chunks(domains: Sequence[str]) -> list[tuple[str, ...]]:
    items = tuple(domains)
    return [items[i : i + MAX_DOMAIN_FILTER] for i in range(0, len(items), MAX_DOMAIN_FILTER)]


@dataclass(frozen=True)
class EvaluationBudget:
    """Per-rule budget (a fresh :class:`RunBudget` per (policy, rule)) plus an optional bound
    on the whole run. Settings: ``NS_POLICY_EVAL_SUBJECT_BUDGET`` (5000) and
    ``NS_POLICY_EVAL_TIME_BUDGET_SECONDS`` (120)."""

    max_subjects_per_rule: int = 5000
    seconds_per_rule: float = 120.0
    run_seconds: float | None = None
    clock: Callable[[], float] = field(default_factory=_monotonic)

    def __post_init__(self) -> None:
        if self.max_subjects_per_rule < 1:
            raise ValueError("max_subjects_per_rule must be at least 1")
        if self.seconds_per_rule <= 0:
            raise ValueError("seconds_per_rule must be positive")
        if self.run_seconds is not None and self.run_seconds <= 0:
            raise ValueError("run_seconds must be positive")

    def rule_budget(self) -> RunBudget:
        return RunBudget.start(self.max_subjects_per_rule, self.seconds_per_rule, clock=self.clock)


@dataclass(frozen=True)
class EvaluationRun:
    """What one run did: the stored status plus ids and counts the status document omits."""

    status: EvaluationStatus
    opened_violation_ids: tuple[str, ...] = ()
    resolved_violation_ids: tuple[str, ...] = ()
    exceptions: ExceptionSyncSummary | None = None
    reconciled: tuple[ReconcileOutcome, ...] = ()

    @property
    def run_id(self) -> str:
        return self.status.run_id

    @property
    def state(self) -> EvaluationRunState:
        return self.status.state


@dataclass
class _RunState:
    """Mutable accumulator of one run (private)."""

    rules: list[RuleRunStatus] = field(default_factory=list)
    evaluated: dict[str, None] = field(default_factory=dict)
    skipped: dict[str, None] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    subjects: int = 0
    reconciled: list[ReconcileOutcome] = field(default_factory=list)


class PolicyEvaluator:
    """Evaluates every published policy in a scope (see the module docstring)."""

    def __init__(
        self,
        policies: PolicyDefinitionStore,
        violations: ViolationStore,
        statuses: EvaluationStatusStore,
        registry: RuleEvaluatorRegistry,
        audit: AuditRepository,
        *,
        events: ViolationEventSink | None = None,
        exceptions: ExceptionReconciler | None = None,
        lifecycle: PolicyLifecycle | None = None,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _uuid4,
    ) -> None:
        self._policies = policies
        self._violations = violations
        self._statuses = statuses
        self._registry = registry
        self._audit = audit
        self._events = events or NoopViolationEventSink()
        self._exceptions = exceptions
        self._lifecycle = lifecycle
        self._clock = clock
        self._ids = id_factory

    @property
    def registry(self) -> RuleEvaluatorRegistry:
        return self._registry

    async def run(
        self,
        customer_id: str,
        *,
        scope: IdentityScope,
        trigger: EvaluationTrigger,
        budget: EvaluationBudget,
        correlation_id: str | None = None,
    ) -> EvaluationRun:
        """Evaluate every published policy the scope covers once; see the module docstring."""
        if scope.customer_id != customer_id:
            raise ForbiddenError("the scope belongs to another customer")
        run_id = self._ids()
        # Dashless: the audit content guard reads a GUID-shaped correlation id as an object id.
        correlation = correlation_id or "govpolicy-eval-" + run_id.replace("-", "")
        started = self._clock()
        control = customer_control_domain_id(scope.cloud, customer_id)
        chain = governance_policy_chain_id(customer_id)
        run_ctx = self._context(scope, correlation, OPERATION_EVALUATION_RUN)
        run_subject = make_subject(
            ":".join(
                (scope.cloud, customer_id, NEUROSPHERE_SOURCE, EVALUATION_RUN_ENTITY_TYPE, run_id)
            ),
            EVALUATION_RUN_ENTITY_TYPE,
        )
        await self._audit.append(chain, build_before(run_ctx, run_subject))
        base = {
            "run_id": run_id,
            "cloud": scope.cloud,
            "customer_id": customer_id,
            "domain_id": control,
            "trigger": trigger,
            "started_at": _timestamp(started),
            "correlation_id": correlation,
        }
        await self._statuses.record(EvaluationStatus.model_validate({**base, "state": "running"}))
        acc = _RunState()
        deadline = (
            None if budget.run_seconds is None else budget.clock() + float(budget.run_seconds)
        )
        exceptions: ExceptionSyncSummary | None = None
        try:
            published = await self._policies.list_published(customer_id)
            visible = tuple(d for d in scope.allowed_domains)
            for stored in published:
                await self._policy(
                    scope,
                    stored.policy,
                    control,
                    visible,
                    budget,
                    deadline,
                    run_id,
                    correlation,
                    acc,
                )
            if self._exceptions is not None:
                exceptions = await self._exceptions.sync(
                    scope, visible, now=self._clock(), correlation_id=correlation
                )
        except Exception as exc:
            reason = _reason(exc, _STORE_UNAVAILABLE)
            _log.warning("govpolicy_evaluation_failed run_id=%s reason=%s", run_id, reason)
            final = self._final(base, acc, "failed", reason)
            try:
                await self._finish(chain, run_ctx, run_subject, final, failed=True)
            except Exception as finish_exc:  # keep the original error; the next tick retries
                _log.warning(
                    "govpolicy_evaluation_status_failed run_id=%s reason=%s",
                    run_id,
                    type(finish_exc).__name__,
                )
            raise
        state, reason_code = self._state(acc)
        final = self._final(base, acc, state, reason_code)
        await self._finish(chain, run_ctx, run_subject, final, failed=False)
        return EvaluationRun(
            status=final,
            opened_violation_ids=tuple(acc.opened),
            resolved_violation_ids=tuple(acc.resolved),
            exceptions=exceptions,
            reconciled=tuple(acc.reconciled),
        )

    # -- one policy -----------------------------------------------------------------------------

    async def _policy(
        self,
        scope: IdentityScope,
        policy: PolicyDefinition,
        control: str,
        visible: tuple[str, ...],
        budget: EvaluationBudget,
        deadline: float | None,
        run_id: str,
        correlation: str,
        acc: _RunState,
    ) -> None:
        domain = policy.domain_id.root
        if domain == control:
            targets = tuple(d for d in visible if d != control)
        elif domain in visible:
            targets = (domain,)
        else:
            acc.skipped[domain] = None
            for rule in policy.rules:
                self._add_rule(acc, policy, rule, "skipped", DOMAIN_OUT_OF_SCOPE)
            return
        if policy.mode is not None and policy.mode.root == "off":
            for rule in policy.rules:
                self._add_rule(acc, policy, rule, "skipped", POLICY_MODE_OFF)
            return
        for target in targets:
            acc.evaluated[target] = None
        if self._lifecycle is not None:
            try:
                acc.reconciled.append(await self._lifecycle.reconcile(scope, policy))
            except Exception as exc:
                _log.warning(
                    "govpolicy_reconcile_failed policy_id=%s reason=%s",
                    policy.policy_id.root,
                    _reason(exc, "reconcile_failed"),
                )
        for rule in policy.rules:
            if deadline is not None and budget.clock() >= deadline:
                self._add_rule(acc, policy, rule, "truncated", RUN_TIME_BUDGET)
                continue
            await self._rule(
                scope, policy, rule, targets, visible, budget, run_id, correlation, acc
            )

    # -- one rule -------------------------------------------------------------------------------

    async def _rule(
        self,
        scope: IdentityScope,
        policy: PolicyDefinition,
        rule: PolicyRule,
        targets: tuple[str, ...],
        visible: tuple[str, ...],
        budget: EvaluationBudget,
        run_id: str,
        correlation: str,
        acc: _RunState,
    ) -> None:
        kind = rule.kind.root
        evaluator = self._registry.get(kind)
        if evaluator is None:
            reason = self._registry.unavailable_reason(kind) or "no_evaluator"
            self._add_rule(acc, policy, rule, "evaluator_unavailable", reason)
            return
        now = self._clock()
        ctx = RuleContext(scope=scope, domain_ids=targets, now=now, budget=budget.rule_budget())
        try:
            outcome = await evaluator.evaluate(ctx, policy, rule)
        except RuleEvaluationError as exc:
            self._add_rule(acc, policy, rule, "failed", _reason_text(exc.reason))
            return
        except Exception as exc:
            _log.warning(
                "govpolicy_rule_failed policy_id=%s rule_id=%s reason=%s",
                policy.policy_id.root,
                rule.rule_id.root,
                type(exc).__name__,
            )
            self._add_rule(acc, policy, rule, "failed", _reason(exc, EVALUATOR_FAILED))
            return
        acc.subjects += outcome.subjects_examined
        opened = 0
        try:
            for finding in outcome.findings:
                if await self._observe(
                    scope, policy, rule, finding, visible, now, run_id, correlation, acc
                ):
                    opened += 1
        except Exception as exc:
            _log.warning(
                "govpolicy_violation_write_failed policy_id=%s rule_id=%s reason=%s",
                policy.policy_id.root,
                rule.rule_id.root,
                type(exc).__name__,
            )
            self._add_rule(
                acc,
                policy,
                rule,
                "failed",
                _reason(exc, VIOLATION_WRITE_FAILED),
                outcome=outcome,
                opened=opened,
            )
            return
        if outcome.truncated:
            self._add_rule(
                acc,
                policy,
                rule,
                "truncated",
                outcome.reason or "truncated",
                outcome=outcome,
                opened=opened,
            )
            return
        resolved = 0
        truncated = False
        try:
            for chunk in _chunks(visible):
                report = await self._violations.resolve_missing_report(
                    scope.customer_id,
                    chunk,
                    run_id=run_id,
                    policy_id=policy.policy_id.root,
                    rule_id=rule.rule_id.root,
                    now=self._clock(),
                )
                truncated = truncated or report.truncated
                for stored in report.resolved:
                    await self._resolved(scope, stored, correlation, acc)
                    resolved += 1
        except Exception as exc:
            _log.warning(
                "govpolicy_resolve_failed policy_id=%s rule_id=%s reason=%s",
                policy.policy_id.root,
                rule.rule_id.root,
                type(exc).__name__,
            )
            self._add_rule(
                acc,
                policy,
                rule,
                "failed",
                _reason(exc, VIOLATION_WRITE_FAILED),
                outcome=outcome,
                opened=opened,
                resolved=resolved,
            )
            return
        self._add_rule(
            acc,
            policy,
            rule,
            "truncated" if truncated else "complete",
            RESOLVE_TRUNCATED if truncated else None,
            outcome=outcome,
            opened=opened,
            resolved=resolved,
        )

    async def _observe(
        self,
        scope: IdentityScope,
        policy: PolicyDefinition,
        rule: PolicyRule,
        finding: RuleFinding,
        visible: tuple[str, ...],
        now: datetime,
        run_id: str,
        correlation: str,
        acc: _RunState,
    ) -> bool:
        """Upsert one finding; True when it opened a new violation."""
        domain = finding.domain_id or policy.domain_id.root
        if domain not in visible:
            return False  # never file a violation in a domain the scope cannot see
        observed_at = _timestamp(now)
        severity = rule.severity.root if rule.severity is not None else policy.severity.root
        observation = ViolationObservation(
            cloud=cast(Literal["commercial", "government"], policy.cloud.root),
            customer_id=policy.customer_id.root,
            domain_id=domain,
            policy_id=policy.policy_id.root,
            policy_version=policy.policy_version,
            rule_id=rule.rule_id.root,
            rule_kind=cast(RuleKindName, rule.kind.root),
            severity=severity,
            subject=TargetRef(canonical_id=finding.subject_id, entity_type=finding.subject_type),
            evidence_class=finding.evidence_class,
            evidence=tuple(e.to_violation_evidence(observed_at) for e in finding.evidence),
            run_id=run_id,
            correlation_id=correlation,
        )
        key = dedup_key(
            observation.policy_id,
            observation.rule_id,
            finding.subject_id,
            finding.evidence_class,
        )
        result = await self._violations.upsert_observed(key, observation, now=now)
        if not result.created:
            return False
        violation = result.stored.violation
        acc.opened.append(violation.violation_id.root)
        await self._audit_violation(scope, violation, correlation, OPERATION_VIOLATION_OPEN)
        await self._emit(VIOLATION_OPENED, violation, correlation)
        return True

    async def _resolved(
        self, scope: IdentityScope, stored: StoredViolation, correlation: str, acc: _RunState
    ) -> None:
        violation = stored.violation
        acc.resolved.append(violation.violation_id.root)
        await self._audit_violation(scope, violation, correlation, OPERATION_VIOLATION_RESOLVE)
        await self._emit(VIOLATION_RESOLVED, violation, correlation)

    # -- audit, events, status ------------------------------------------------------------------

    @staticmethod
    def _context(scope: IdentityScope, correlation: str, operation: str) -> AuditContext:
        return AuditContext.from_scope(
            scope, correlation_id=correlation, operation=operation, channel="worker"
        )

    async def _audit_violation(
        self, scope: IdentityScope, violation: PolicyViolation, correlation: str, operation: str
    ) -> None:
        subject = make_subject(
            violation_canonical_id(
                violation.cloud.root, violation.customer_id.root, violation.violation_id.root
            ),
            POLICY_VIOLATION_ENTITY_TYPE,
            state={
                "status": violation.status,
                "dedup_key": violation.dedup_key,
                "policy_id": violation.policy_id.root,
                "policy_version": violation.policy_version,
                "rule_id": violation.rule_id.root,
            },
        )
        ctx = self._context(scope, correlation, operation)
        await self._audit.append(
            governance_policy_chain_id(violation.customer_id.root),
            build_after(
                ctx, subject, result="succeeded", verified=True, detail=f"status={violation.status}"
            ),
        )

    async def _emit(self, event_class: str, violation: PolicyViolation, correlation: str) -> None:
        event = ViolationEvent(
            event_class=cast(
                Literal["policy_violation_opened", "policy_violation_resolved"], event_class
            ),
            cloud=violation.cloud.root,
            customer_id=violation.customer_id.root,
            domain_id=violation.domain_id.root,
            violation_id=violation.violation_id.root,
            policy_id=violation.policy_id.root,
            policy_version=violation.policy_version,
            rule_id=violation.rule_id.root,
            subject_id=violation.subject.canonical_id,
            severity=violation.severity.root,
            correlation_id=correlation,
        )
        try:
            if event_class == VIOLATION_OPENED:
                await self._events.opened(event)
            else:
                await self._events.resolved(event)
        except Exception as exc:
            _log.warning("govpolicy_event_sink_failed reason=%s", type(exc).__name__)

    @staticmethod
    def _add_rule(
        acc: _RunState,
        policy: PolicyDefinition,
        rule: PolicyRule,
        outcome_name: RuleOutcomeName,
        reason: str | None,
        *,
        outcome: RuleOutcome | None = None,
        opened: int = 0,
        resolved: int = 0,
    ) -> None:
        acc.rules.append(
            RuleRunStatus(
                policy_id=policy.policy_id.root,
                policy_version=policy.policy_version,
                rule_id=rule.rule_id.root,
                rule_kind=cast(RuleKindName, rule.kind.root),
                outcome=outcome_name,
                reason_code=reason,
                subjects_evaluated=outcome.subjects_examined if outcome is not None else 0,
                findings=len(outcome.findings) if outcome is not None else 0,
                violations_opened=opened,
                violations_resolved=resolved,
            )
        )

    @staticmethod
    def _state(acc: _RunState) -> tuple[EvaluationRunState, str | None]:
        outcomes = [r.outcome for r in acc.rules]
        if "failed" in outcomes:
            failed = next(r for r in acc.rules if r.outcome == "failed")
            return "failed", failed.reason_code
        if "truncated" in outcomes:
            return "truncated", "truncated"
        return "completed", None

    def _final(
        self,
        base: dict[str, str],
        acc: _RunState,
        state: EvaluationRunState,
        reason: str | None,
    ) -> EvaluationStatus:
        return EvaluationStatus.model_validate(
            {
                **base,
                "state": state,
                "finished_at": _timestamp(self._clock()),
                "reason_code": reason,
                "rules": [r.model_dump() for r in acc.rules[:MAX_RULE_STATUSES]],
                "domains_evaluated": list(acc.evaluated)[:MAX_SKIPPED_DOMAINS],
                "domains_skipped": list(acc.skipped)[:MAX_SKIPPED_DOMAINS],
                "subjects_evaluated": min(acc.subjects, 10_000_000),
                "violations_opened": len(acc.opened),
                "violations_resolved": len(acc.resolved),
            }
        )

    async def _finish(
        self,
        chain: str,
        ctx: AuditContext,
        subject: Subject,
        final: EvaluationStatus,
        *,
        failed: bool,
    ) -> None:
        detail = (
            f"state={final.state}:rules={len(final.rules)}:opened={final.violations_opened}:"
            f"resolved={final.violations_resolved}:skipped_domains={len(final.domains_skipped)}"
        )
        try:
            await self._statuses.record(final)
        finally:
            await self._audit.append(
                chain,
                build_after(
                    ctx,
                    subject,
                    result="failed" if failed else "succeeded",
                    verified=not failed,
                    detail=detail,
                ),
            )
