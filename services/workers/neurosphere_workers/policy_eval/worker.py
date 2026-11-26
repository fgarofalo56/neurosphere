"""The ``policy_eval`` tick (PRP-105 item 5, acceptance criteria 2, 3 and 4 tick side).

The runtime calls :meth:`PolicyEvalWorker.tick` every ``NS_WORKER_POLL_SECONDS``. Most calls only
check the clock. A run happens when either

* the interval (``NS_POLICY_EVAL_INTERVAL_SECONDS``) has passed since the last run (trigger
  ``interval``; the first tick after start always runs), or
* a policy was published since the last successful run started (trigger ``due``). The check is a
  bounded ``list_published`` read at most every :data:`DUE_CHECK_SECONDS`.

Every run evaluates every published policy the worker's own derived scope covers (that is what
:meth:`PolicyEvaluator.run` does). "Due first": :class:`DueFirstPolicies` hands the evaluator the
policies published since the last run ahead of the rest, so a newly published policy is looked at
before older ones when the run's time budget runs out.

The run itself writes the audit records (``govpolicy.evaluation_run``, ``violation_open``,
``violation_resolve``, ``exception_decide``) and the run status document; this module writes no
audit of its own and never resolves, opens or excepts anything directly.

Failure: a store outage, a scope lookup failure or any other error RELEASES the tick. The reason
code is logged (class name and reason code only, never a document), nothing escapes the tick, and
the role retries after :data:`RETRY_SECONDS` (bounded by the interval) instead of a hot loop.
Policies that were due stay due, because the "last run" mark only moves on a run that returned.
A run that returned with state ``failed`` or ``truncated`` (one rule failed or hit its budget) is
a finished run: its status document says why, nothing was resolved for that rule, and the rule is
looked at again on the next interval (not sooner, so a rule that keeps failing is not hammered).
"""

from __future__ import annotations

import builtins
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.governance.policy import (
    EvaluationBudget,
    EvaluationRun,
    PolicyDefinitionStore,
    PolicyEvaluator,
    StoredPolicy,
)
from neurosphere_core.governance.policy.models import EvaluationTrigger, PolicyDefinition
from neurosphere_core.governance.policy.rules import ScopeProvider
from neurosphere_core.governance.policy.store import MAX_VERSIONS
from neurosphere_core.paging import Page, PageRequest

__all__ = [
    "DUE_CHECK_SECONDS",
    "POLICY_STORE_UNAVAILABLE",
    "RETRY_SECONDS",
    "ROLE_NAME",
    "SCOPE_CUSTOMER_MISMATCH",
    "WORKER_SCOPE_UNAVAILABLE",
    "DueFirstPolicies",
    "PolicyEvalWorker",
    "TickOutcome",
]

ROLE_NAME: Final = "policy_eval"
DUE_CHECK_SECONDS: Final = 30.0
"""How often (at most) the role looks for policies published since its last run."""
RETRY_SECONDS: Final = 60.0
"""Wait after a released tick before trying again (never longer than the interval)."""

POLICY_STORE_UNAVAILABLE: Final = "policy_store_unavailable"
WORKER_SCOPE_UNAVAILABLE: Final = "worker_scope_unavailable"
SCOPE_CUSTOMER_MISMATCH: Final = "worker_scope_customer_mismatch"
EVALUATION_FAILED: Final = "policy_evaluation_failed"

_REASON_CODE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

TickAction = Literal["ran", "waiting", "released"]
Clock = Callable[[], datetime]

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reason(exc: BaseException, default: str) -> str:
    """The error's snake_case reason code, else ``default`` (never free text)."""
    reason = getattr(exc, "reason", None) if isinstance(exc, NeuroSphereError) else None
    return reason if isinstance(reason, str) and _REASON_CODE.fullmatch(reason) else default


def _parse_timestamp(value: str) -> datetime:
    """A contract ``Timestamp`` (``...Z``, up to 9 fraction digits) as an aware datetime."""
    body = value.removesuffix("Z")
    whole, _, fraction = body.partition(".")
    text = f"{whole}.{fraction[:6]}" if fraction else whole
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def published_after(policy: PolicyDefinition, since: datetime | None) -> bool:
    """True when ``policy`` was published after ``since`` (always True for ``since=None``)."""
    if since is None:
        return True
    stamp = policy.published_at
    if stamp is None:
        return False
    try:
        return _parse_timestamp(stamp.root) > since
    except ValueError:
        return False


class DueFirstPolicies:
    """A :class:`PolicyDefinitionStore` whose ``list_published`` puts due policies first.

    "Due" means published after the mark set by :meth:`prioritise` (the start of the last
    successful run). Everything else delegates unchanged to the wrapped store; the order inside
    each group stays the store's (policy id).
    """

    def __init__(self, inner: PolicyDefinitionStore) -> None:
        self._inner = inner
        self._since: datetime | None = None

    @property
    def inner(self) -> PolicyDefinitionStore:
        return self._inner

    def prioritise(self, since: datetime | None) -> None:
        """Order policies published after ``since`` first (``None``: store order)."""
        self._since = since

    async def due(self, customer_id: str, since: datetime | None) -> tuple[str, ...]:
        """Ids of the published policies that were published after ``since``."""
        published = await self._inner.list_published(customer_id)
        return tuple(s.policy.policy_id.root for s in published if published_after(s.policy, since))

    async def list_published(
        self,
        customer_id: str,
        domain_ids: Sequence[str] | None = None,
        *,
        limit: int = MAX_VERSIONS,
    ) -> builtins.list[StoredPolicy]:
        rows = await self._inner.list_published(customer_id, domain_ids, limit=limit)
        since = self._since
        if since is None:
            return rows
        due = [r for r in rows if published_after(r.policy, since)]
        rest = [r for r in rows if not published_after(r.policy, since)]
        return due + rest

    async def create_draft(self, policy: PolicyDefinition | Mapping[str, Any]) -> StoredPolicy:
        return await self._inner.create_draft(policy)

    async def replace_draft(
        self, policy: PolicyDefinition | Mapping[str, Any], *, if_match: str
    ) -> StoredPolicy:
        return await self._inner.replace_draft(policy, if_match=if_match)

    async def get(
        self, customer_id: str, policy_id: str, *, version: int | None = None
    ) -> StoredPolicy | None:
        return await self._inner.get(customer_id, policy_id, version=version)

    async def list(
        self, customer_id: str, domain_ids: Sequence[str], page: PageRequest
    ) -> Page[StoredPolicy]:
        return await self._inner.list(customer_id, domain_ids, page)

    async def versions(
        self, customer_id: str, policy_id: str, *, limit: int = 100
    ) -> builtins.list[StoredPolicy]:
        return await self._inner.versions(customer_id, policy_id, limit=limit)

    async def mark_published(
        self,
        customer_id: str,
        policy_id: str,
        version: int,
        *,
        if_match: str,
        published_at: datetime,
        intent_id: str,
        audit_id: str,
    ) -> StoredPolicy:
        return await self._inner.mark_published(
            customer_id,
            policy_id,
            version,
            if_match=if_match,
            published_at=published_at,
            intent_id=intent_id,
            audit_id=audit_id,
        )

    async def mark_retired(
        self, customer_id: str, policy_id: str, version: int, *, if_match: str
    ) -> StoredPolicy:
        return await self._inner.mark_retired(customer_id, policy_id, version, if_match=if_match)


@dataclass(frozen=True, slots=True)
class TickOutcome:
    """What one tick did: ``ran`` (with the run), ``waiting`` or ``released`` (with a reason)."""

    action: TickAction
    trigger: EvaluationTrigger | None = None
    reason_code: str | None = None
    run: EvaluationRun | None = None
    due_policies: int = 0


class PolicyEvalWorker:
    """Paces :meth:`PolicyEvaluator.run` (see the module docstring)."""

    def __init__(
        self,
        evaluator: PolicyEvaluator,
        policies: DueFirstPolicies,
        scope_provider: ScopeProvider,
        *,
        customer_id: str,
        interval_seconds: float,
        subject_budget: int,
        time_budget_seconds: float,
        due_check_seconds: float = DUE_CHECK_SECONDS,
        retry_seconds: float = RETRY_SECONDS,
        clock: Clock = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._evaluator = evaluator
        self._policies = policies
        self._scopes = scope_provider
        self._customer = customer_id
        self._interval = float(interval_seconds)
        self._subjects = subject_budget
        self._seconds = float(time_budget_seconds)
        self._due_check = min(float(due_check_seconds), self._interval)
        self._retry = min(float(retry_seconds), self._interval)
        self._clock = clock
        self._monotonic = monotonic
        self._next_run: float | None = None
        self._next_due_check: float | None = None
        self._last_started: datetime | None = None

    @property
    def last_started(self) -> datetime | None:
        """Wall-clock start of the last successful run (the "due" mark)."""
        return self._last_started

    async def tick(self) -> TickOutcome:
        """One poll: maybe run, never raise (a failure is logged and released)."""
        now = self._monotonic()
        interval_due = self._next_run is None or now >= self._next_run
        if not interval_due and self._next_due_check is not None and now < self._next_due_check:
            return TickOutcome("waiting")
        self._next_due_check = now + self._due_check
        try:
            scope = await self._scopes.get()
        except Exception as exc:
            return self._release(now, _reason(exc, WORKER_SCOPE_UNAVAILABLE), exc)
        if scope.customer_id != self._customer:
            return self._release(now, SCOPE_CUSTOMER_MISMATCH, None)
        try:
            due = await self._policies.due(self._customer, self._last_started)
        except Exception as exc:
            return self._release(now, _reason(exc, POLICY_STORE_UNAVAILABLE), exc)
        if not interval_due and not due:
            return TickOutcome("waiting")
        trigger: EvaluationTrigger = "interval" if interval_due else "due"
        started = self._clock()
        # Stamp before the run: a slow or failing run never turns into a hot loop.
        self._next_run = now + self._interval
        self._policies.prioritise(self._last_started)
        try:
            run = await self._evaluator.run(
                self._customer,
                scope=scope,
                trigger=trigger,
                budget=EvaluationBudget(
                    max_subjects_per_rule=self._subjects,
                    seconds_per_rule=self._seconds,
                    clock=self._monotonic,
                ),
            )
        except Exception as exc:
            return self._release(now, _reason(exc, EVALUATION_FAILED), exc, trigger=trigger)
        finally:
            self._policies.prioritise(None)
        self._last_started = started
        status = run.status
        _log.info(
            "policy evaluation run finished",
            extra={
                "event": "worker.policy_eval_run",
                "run_id": status.run_id,
                "trigger": trigger,
                "state": status.state,
                "reason": status.reason_code,
                "due_policies": len(due),
                "rules": len(status.rules),
                "subjects_evaluated": status.subjects_evaluated,
                "violations_opened": status.violations_opened,
                "violations_resolved": status.violations_resolved,
                "domains_skipped": len(status.domains_skipped),
            },
        )
        return TickOutcome(
            "ran", trigger=trigger, reason_code=status.reason_code, run=run, due_policies=len(due)
        )

    def _release(
        self,
        now: float,
        reason: str,
        exc: BaseException | None,
        *,
        trigger: EvaluationTrigger | None = None,
    ) -> TickOutcome:
        self._next_run = now + self._retry
        self._next_due_check = now + self._retry
        _log.warning(
            "policy evaluation tick released",
            extra={
                "event": "worker.policy_eval_released",
                "reason": reason,
                "error": type(exc).__name__ if exc is not None else None,
            },
        )
        return TickOutcome("released", trigger=trigger, reason_code=reason)
