"""``ActionExecutor``: the ONLY code in the repo that calls ``WriteConnector.apply``/``rollback``.

One durable executor for button, chat, REST and MCP intents (PRP-17 item 2). It never changes
intent state itself: every state change and every phase record goes through
:class:`~neurosphere_core.actions.ActionService` (ETag-conditional, audited).

Per intent in ``executing`` (delta D4)::

    kill switch -> claim (lease) -> recheck (kill switch, binding, maker's action.execute)
    -> dry_run (current target version) -> kill switch -> audit before + phase ``applying``
    -> apply -> phase ``applied`` + audit after -> canary probe -> verify + audit after
    -> succeeded            (canary/verify failure -> rollback -> rolled_back | failed)

Crash safety. Phase ``applying`` is persisted BEFORE ``apply``; ``apply_result`` right after.
A restarted executor reads the record: once ``apply_may_have_happened()`` it NEVER applies
again. With an ``apply_result`` it resumes at canary/verify (and rolls back if needed); without
one (crash mid-apply, or the post-apply write was lost) it verifies against the target to
discover the outcome: matched -> continue (with a discovered apply result that has no rollback
token), not matched -> ``failed`` (``apply_not_observed``, flagged for the operator).

Lease. The claim's lease is renewed on every phase write AND, while ``connector.apply`` or
``connector.rollback`` is in flight, by a renewal task (ETag'd ``record_execution``, phase
unchanged) every ``lease_renewal``. The lease must outlive ``max_connector_call`` on its own, so
even a stalled renewal cannot hand an in-flight apply to another worker. If a renewal loses the
ETag race (another worker took the intent), this executor finalizes NOTHING afterwards: the
pass ends ``skipped`` ``lease_lost`` and the new owner discovers the outcome by verify. Defence
in depth: recovery that sees no apply result and an unmatched target while the apply window
(``max(apply_started_at, last renewal) + lease``) is still open DEFERS instead of failing.

Emergency disable (mandatory ``ExecutionControl``): checked before claiming and again right
before apply. Disabled or control-store outage = no connector call, intent left in
``executing`` with its lease released and its phase unchanged; it resumes when re-enabled.

Transient failures (policy store outage, connector ``retryable`` errors, store outage) release
the lease and leave the phase as is; the next pass resumes. Another worker winning an ETag race
or holding a live lease ends this pass with ``skipped``.

Nothing secret is written: records hold connector result metadata, machine reason codes and
digests; logs carry the intent id, phase and reason only (never principal ids or tokens).
Success is only ``VerifyResult.matched`` read back from the target; no catalog metadata is
touched here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from neurosphere_connector.write import (
    ApplyResult,
    VerifyResult,
    WriteConnector,
    WriteRequest,
    WriteTargetRegistry,
)
from neurosphere_core.actions import (
    ActionService,
    ExecutionControl,
    ExecutionRecord,
    IntentKey,
    IntentNotFoundError,
    StoredIntent,
    require_execution_enabled,
)
from neurosphere_core.actions.errors import TARGET_VERSION_CHANGED
from neurosphere_core.audit.builders import OutcomeResult
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.errors import CapabilityUnavailableError, NeuroSphereError, StaleVersionError
from pydantic import ValidationError

from neurosphere_workers.actions.canary import CANARY_OUTCOMES, CanaryProbe, VerifyOnlyCanary
from neurosphere_workers.actions.completion import FinishedHook
from neurosphere_workers.actions.targets import DEFAULT_ACTION_CONNECTORS, resolve_connector

__all__ = [
    "APPLY_FAILED_RESTORED",
    "APPLY_FAILED_RESTORE_FAILED",
    "APPLY_NOT_OBSERVED",
    "APPLY_WINDOW_OPEN",
    "DEFAULT_LEASE",
    "DEFAULT_LEASE_RENEWAL",
    "DEFAULT_MAX_CONNECTOR_CALL",
    "LEASE_LOST",
    "ROLLBACK_FAILED",
    "ActionExecutor",
    "ExecutionReport",
    "ReportOutcome",
]

logger = logging.getLogger("neurosphere.workers.actions")

APPLY_FAILED_RESTORED: Final = "apply_failed_restored"
APPLY_FAILED_RESTORE_FAILED: Final = "apply_failed_restore_failed"
APPLY_NOT_OBSERVED: Final = "apply_not_observed"
APPLY_WINDOW_OPEN: Final = "apply_window_open"
LEASE_LOST: Final = "lease_lost"
ROLLBACK_FAILED: Final = "rollback_failed"
CANARY_FAILED: Final = "canary_failed"
VERIFICATION_FAILED: Final = "verification_failed"
CAPABILITY_UNAVAILABLE: Final = "capability_unavailable"
_TERMINAL_STATES: Final = frozenset({"succeeded", "failed", "rolled_back", "expired"})
_REASON_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LEASE_RENEWED_AT: Final = "lease_renewed_at"

# The longest a single connector apply/rollback call may take (Foundry: GETs + PUT + up to 300 s
# provisioning poll, and on failure a restore PUT + another 300 s). The lease must outlive it
# even without renewals; renewals run well inside the lease.
DEFAULT_MAX_CONNECTOR_CALL: Final = timedelta(minutes=15)
DEFAULT_LEASE: Final = timedelta(minutes=20)
DEFAULT_LEASE_RENEWAL: Final = timedelta(minutes=1)

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]
ReportOutcome = Literal["succeeded", "failed", "rolled_back", "deferred", "skipped"]
_FINAL_OUTCOME: Final[Mapping[str, ReportOutcome]] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "rolled_back": "rolled_back",
    "expired": "failed",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reason(exc: BaseException) -> str:
    """Machine reason of an error (never free text): its ``reason`` or taxonomy ``code``."""
    if isinstance(exc, NeuroSphereError):
        if isinstance(exc.reason, str) and _REASON_RE.fullmatch(exc.reason):
            return exc.reason
        return exc.code
    return "connector_error"


def _wire(applied: ApplyResult) -> dict[str, Any]:
    """Round-trippable JSON of an apply result (``by_alias``: patch ``from`` is aliased)."""
    return applied.model_dump(mode="json", by_alias=True)


def _retryable(exc: BaseException) -> bool:
    return not isinstance(exc, NeuroSphereError) or exc.retryable


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """What one executor pass did. ``deferred``: left in ``executing`` for a later pass."""

    intent_id: str
    outcome: ReportOutcome
    reason: str | None = None
    state: str | None = None


class _Halt(Exception):  # noqa: N818 - control flow, never escapes the executor
    def __init__(self, report: ExecutionReport) -> None:
        super().__init__(report.outcome)
        self.report = report


class _LeaseKeeper:
    """Extends the lease every ``interval`` while one connector call is in flight.

    Each renewal is an ETag'd ``record_execution`` (phase unchanged) and carries the fresh ETag
    forward in :attr:`stored`. A stale ETag means another worker (or writer) took the intent:
    :attr:`lost` is set and renewing stops. Any other failure is logged and retried on the next
    tick (the lease alone already outlives a declared maximum connector call). A renewal write in
    flight when the call returns is awaited, never abandoned, so the ETag stays known.
    """

    def __init__(
        self,
        renew: Callable[[StoredIntent], Awaitable[StoredIntent]],
        stored: StoredIntent,
        *,
        interval: timedelta,
        sleep: Sleep,
    ) -> None:
        self.stored = stored
        self.lost = False
        self._renew = renew
        self._interval = interval.total_seconds()
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._write: asyncio.Future[bool] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        write = self._write
        if write is not None:
            await write

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._interval)
            write = asyncio.ensure_future(self._renew_once())
            self._write = write
            alive = await asyncio.shield(write)
            self._write = None
            if not alive:
                return

    async def _renew_once(self) -> bool:
        try:
            self.stored = await self._renew(self.stored)
        except StaleVersionError:
            self.lost = True
            return False
        except Exception as exc:  # store outage: try again next tick
            logger.warning(
                "lease renewal failed; retrying",
                extra={
                    "event": "action.lease_renewal_failed",
                    "intent_id": self.stored.intent_id,
                    "reason": _reason(exc),
                },
            )
        return True


class ActionExecutor:
    """Runs ``executing`` intents through a write connector. See the module docstring.

    ``execution_control`` is REQUIRED (no default): the kill switch cannot be wired away.
    ``action_connectors`` maps ``action_kind`` to a connector manifest name in ``registry``.
    ``worker_id`` names the lease owner. ``lease`` is renewed on every phase write and every
    ``lease_renewal`` while a connector apply/rollback runs; it must be at least
    ``max_connector_call`` (the declared longest single connector call) and more than twice
    ``lease_renewal``. ``sleep`` paces renewals (injectable for tests).
    """

    def __init__(
        self,
        service: ActionService,
        registry: WriteTargetRegistry,
        *,
        execution_control: ExecutionControl,
        worker_id: str,
        action_connectors: Mapping[str, str] = DEFAULT_ACTION_CONNECTORS,
        canary: CanaryProbe | None = None,
        clock: Clock = _utc_now,
        lease: timedelta = DEFAULT_LEASE,
        lease_renewal: timedelta = DEFAULT_LEASE_RENEWAL,
        max_connector_call: timedelta = DEFAULT_MAX_CONNECTOR_CALL,
        sleep: Sleep = asyncio.sleep,
        on_finished: FinishedHook | None = None,
    ) -> None:
        if not isinstance(execution_control, ExecutionControl):
            raise TypeError("execution_control is required: the emergency disable is mandatory")
        if not worker_id:
            raise ValueError("worker_id is required")
        if lease <= timedelta(0) or lease_renewal <= timedelta(0):
            raise ValueError("lease and lease_renewal must be positive")
        if max_connector_call <= timedelta(0):
            raise ValueError("max_connector_call must be positive")
        if lease < max_connector_call:
            raise ValueError("lease must be at least max_connector_call")
        if lease <= lease_renewal * 2:
            raise ValueError("lease must be more than twice lease_renewal")
        self._service = service
        self._registry = registry
        self._control = execution_control
        self._worker_id = worker_id
        self._table = dict(action_connectors)
        self._canary: CanaryProbe = canary if canary is not None else VerifyOnlyCanary()
        self._clock = clock
        self._lease = lease
        self._renewal = lease_renewal
        self._sleep = sleep
        self._on_finished = on_finished

    @property
    def worker_id(self) -> str:
        return self._worker_id

    # -- entry point -------------------------------------------------------------------------

    async def execute(self, key: IntentKey) -> ExecutionReport:
        """One pass over one intent. Never raises for per-intent conditions.

        When the intent is terminal after the pass (also on a repeat pass over an already
        finished intent, which makes a failed hook retry-safe) the optional ``on_finished`` hook
        runs. A hook failure is logged and never changes the report or the intent.
        """
        report = await self._execute_pass(key)
        if self._on_finished is not None and report.state in _TERMINAL_STATES:
            await self._notify_finished(key, report)
        return report

    async def _notify_finished(self, key: IntentKey, report: ExecutionReport) -> None:
        hook = self._on_finished
        if hook is None:
            return
        try:
            stored = await self._service.get(key)
            if stored.review_item_id is not None:
                await hook(stored, report)
        except Exception as exc:  # never alters the outcome; the next pass retries
            logger.warning(
                "completion hook failed",
                extra={
                    "event": "action.completion_hook_failed",
                    "intent_id": key.intent_id,
                    "reason": _reason(exc),
                },
            )

    async def _execute_pass(self, key: IntentKey) -> ExecutionReport:
        try:
            current = await self._service.get(key)
        except IntentNotFoundError:
            return self._report(key.intent_id, "skipped", "intent_not_found")
        except NeuroSphereError as exc:
            return self._report(key.intent_id, "deferred", _reason(exc))
        if current.state != "executing":
            return self._report(key.intent_id, "skipped", "not_executing", current.state)
        disabled = await self._disabled(current)
        if disabled is not None:
            return self._report(key.intent_id, "deferred", disabled, current.state)
        try:
            stored = await self._service.begin_execution(
                key, worker_id=self._worker_id, lease=self._lease, now=self._now()
            )
        except StaleVersionError as exc:  # live lease elsewhere or lost the claim race
            return self._report(key.intent_id, "skipped", _reason(exc), current.state)
        except NeuroSphereError as exc:
            return self._report(key.intent_id, "deferred", _reason(exc), current.state)
        try:
            return await self._run(stored)
        except _Halt as halt:
            return halt.report

    # -- main flow ---------------------------------------------------------------------------

    async def _run(self, stored: StoredIntent) -> ExecutionReport:
        record = stored.execution or ExecutionRecord()
        touched = record.apply_may_have_happened()
        connector = await self._resolve(stored, after_apply=touched)
        request = WriteRequest(
            target=stored.intent.target,
            target_version=stored.intent.target_version,
            proposed_diff=stored.intent.proposed_diff,
        )
        if touched:
            return await self._resume(stored, connector, request)
        stored = await self._recheck(stored)
        stored = await self._dry_run(stored, connector, request)
        if stored.intent.dry_run:
            return await self._finish(stored, "succeeded")
        disabled = await self._disabled(stored)
        if disabled is not None:
            return await self._release(stored, disabled)
        return await self._apply(stored, connector, request)

    async def _resolve(self, stored: StoredIntent, *, after_apply: bool) -> WriteConnector:
        try:
            if stored.advisory:
                raise CapabilityUnavailableError(CAPABILITY_UNAVAILABLE, "advisory intent")
            return resolve_connector(self._registry, self._table, stored.intent.action_kind)
        except CapabilityUnavailableError:
            details = {"operator_attention": True} if after_apply else None
            raise _Halt(
                await self._finish(stored, "failed", CAPABILITY_UNAVAILABLE, details=details)
            ) from None

    async def _recheck(self, stored: StoredIntent) -> StoredIntent:
        """Kill switch, stored binding and the maker's current ``action.execute`` (service)."""
        try:
            return await self._service.recheck_execution(
                stored, current_target_version=stored.intent.target_version, now=self._now()
            )
        except NeuroSphereError as exc:
            raise _Halt(await self._after_refusal(stored, exc)) from None

    async def _dry_run(
        self, stored: StoredIntent, connector: WriteConnector, request: WriteRequest
    ) -> StoredIntent:
        """Current target version via the connector; nothing is written to the target."""
        try:
            planned = await connector.dry_run(request)
        except StaleVersionError:
            raise _Halt(await self._finish(stored, "failed", TARGET_VERSION_CHANGED)) from None
        except Exception as exc:
            if _retryable(exc):
                raise _Halt(await self._release(stored, _reason(exc))) from None
            raise _Halt(await self._finish(stored, "failed", _reason(exc))) from None
        if planned.target_version != request.target_version or planned.target != request.target:
            raise _Halt(await self._finish(stored, "failed", TARGET_VERSION_CHANGED))
        return await self._save(
            stored,
            phase="dry_run_done",
            dry_run_result={
                "target_version": planned.target_version,
                "would_change": planned.would_change,
            },
        )

    async def _apply(
        self, stored: StoredIntent, connector: WriteConnector, request: WriteRequest
    ) -> ExecutionReport:
        before = sha256_digest(
            {
                "target": request.target.model_dump(mode="json"),
                "target_version": request.target_version,
                "dry_run": (stored.execution or ExecutionRecord()).dry_run_result,
            }
        )
        stored = await self._save(
            stored,
            audit="before",
            target_state_digest=before,
            phase="applying",
            apply_started_at=self._now(),
        )
        logger.info("applying", extra={"event": "action.apply", "intent_id": stored.intent_id})
        stored, applied = await self._leased_call(stored, lambda: connector.apply(request))
        if isinstance(applied, Exception):
            return await self._apply_failed(stored, connector, request, applied)
        stored = await self._save(
            stored,
            audit="after",
            result="succeeded",
            target_state_digest=sha256_digest(_wire(applied)),
            phase="applied",
            apply_result=_wire(applied),
            apply_finished_at=self._now(),
        )
        return await self._canary_and_verify(stored, connector, request, applied)

    async def _apply_failed(
        self,
        stored: StoredIntent,
        connector: WriteConnector,
        request: WriteRequest,
        exc: Exception,
    ) -> ExecutionReport:
        reason = _reason(exc)
        restored = isinstance(exc, CapabilityUnavailableError) and reason in (
            APPLY_FAILED_RESTORED,
            APPLY_FAILED_RESTORE_FAILED,
        )
        details: dict[str, Any] = {"apply_error": reason}
        if restored:
            # The connector already undid its own write: never re-apply, never roll back.
            details["connector_restored"] = reason == APPLY_FAILED_RESTORED
            if reason == APPLY_FAILED_RESTORE_FAILED:
                details["operator_attention"] = True
        stored = await self._save(
            stored,
            audit="after",
            result="failed",
            reason=reason,
            last_error=reason,
            details=details,
        )
        if restored:
            if reason == APPLY_FAILED_RESTORE_FAILED:
                logger.error(
                    "apply failed and the connector could not restore the target",
                    extra={"event": "action.operator_attention", "intent_id": stored.intent_id},
                )
            return await self._finish(stored, "failed", reason)
        # The outcome of an apply that raised is unknown: discover it, never retry it.
        return await self._discover(stored, connector, request, known_error=reason)

    # -- recovery ----------------------------------------------------------------------------

    async def _resume(
        self, stored: StoredIntent, connector: WriteConnector, request: WriteRequest
    ) -> ExecutionReport:
        """An apply may have happened: verify / roll back from the record, never apply again."""
        record = stored.execution or ExecutionRecord()
        logger.info(
            "resuming after a possible apply",
            extra={"event": "action.resume", "intent_id": stored.intent_id, "phase": record.phase},
        )
        if record.rolled_back:
            return await self._finish(stored, "rolled_back", self._rollback_reason(record))
        applied = self._stored_apply(stored, record)
        if (
            record.phase == "rolling_back"
            or record.canary == "failed"
            or (record.verify_matched is False)
        ):
            if applied is None:
                return await self._finish(
                    stored, "failed", ROLLBACK_FAILED, details={"operator_attention": True}
                )
            return await self._rollback(stored, connector, applied, self._rollback_reason(record))
        if applied is None:
            known = record.details.get("apply_error")
            return await self._discover(
                stored, connector, request, known_error=known if isinstance(known, str) else None
            )
        if record.verify_matched is True:
            return await self._finish(stored, "succeeded")
        return await self._canary_and_verify(stored, connector, request, applied)

    async def _discover(
        self,
        stored: StoredIntent,
        connector: WriteConnector,
        request: WriteRequest,
        *,
        known_error: str | None,
    ) -> ExecutionReport:
        """No apply result: read the target to learn whether the change landed."""
        observed = await self._read_back(stored, connector, request)
        if not observed.matched:
            if known_error is None and self._apply_window_open(stored):
                # Another worker's apply may still be in flight (target still provisioning):
                # never call it failed before the apply window has passed.
                logger.info(
                    "apply window still open; deferring discovery",
                    extra={"event": "action.apply_window_open", "intent_id": stored.intent_id},
                )
                return await self._release(stored, APPLY_WINDOW_OPEN)
            reason = known_error or APPLY_NOT_OBSERVED
            details = {"operator_attention": True} if known_error is None else None
            return await self._finish(stored, "failed", reason, details=details)
        applied = ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=observed.observed_version,
            applied_diff=request.proposed_diff,
            rollback_token=None,
        )
        stored = await self._save(
            stored,
            audit="after",
            result="succeeded",
            target_state_digest=sha256_digest(observed.observed_state),
            phase="applied",
            apply_result=_wire(applied),
            apply_finished_at=self._now(),
            details={"apply_result_source": "verify_discovery"},
        )
        return await self._canary_and_verify(stored, connector, request, applied)

    # -- canary, verify, rollback ------------------------------------------------------------

    async def _canary_and_verify(
        self,
        stored: StoredIntent,
        connector: WriteConnector,
        request: WriteRequest,
        applied: ApplyResult,
    ) -> ExecutionReport:
        record = stored.execution or ExecutionRecord()
        if record.canary is None:
            stored = await self._save(stored, phase="canary")
            observed = await self._read_back(stored, connector, request)
            try:
                outcome: str = await self._canary.probe(request, applied, observed)
            except Exception:
                outcome = "failed"
            if outcome not in CANARY_OUTCOMES:
                outcome = "failed"
            stored = await self._save(stored, canary=outcome)
            if outcome == "failed":
                return await self._rollback(stored, connector, applied, CANARY_FAILED)
        stored = await self._save(stored, phase="verifying")
        verified = await self._read_back(stored, connector, request)
        stored = await self._save(
            stored,
            audit="after",
            result="succeeded" if verified.matched else "failed",
            verified=verified.matched,
            reason=None if verified.matched else VERIFICATION_FAILED,
            target_state_digest=sha256_digest(verified.observed_state),
            verify_matched=verified.matched,
            details={"mismatched_paths": list(verified.mismatched_paths)},
        )
        if not verified.matched:
            return await self._rollback(stored, connector, applied, VERIFICATION_FAILED)
        return await self._finish(stored, "succeeded")

    async def _rollback(
        self,
        stored: StoredIntent,
        connector: WriteConnector,
        applied: ApplyResult,
        reason: str,
    ) -> ExecutionReport:
        stored = await self._save(
            stored,
            audit="before",
            reason=reason,
            phase="rolling_back",
            details={"rollback_reason": reason},
        )
        stored, undone = await self._leased_call(stored, lambda: connector.rollback(applied))
        if isinstance(undone, Exception):
            error = _reason(undone)
            stored = await self._save(
                stored,
                audit="after",
                result="failed",
                reason=ROLLBACK_FAILED,
                rollback_result={"error": error},
                details={"operator_attention": True},
            )
            logger.error(
                "rollback failed",
                extra={"event": "action.operator_attention", "intent_id": stored.intent_id},
            )
            return await self._finish(stored, "failed", ROLLBACK_FAILED)
        stored = await self._save(
            stored,
            audit="after",
            result="rolled_back",
            reason=reason,
            rolled_back=True,
            rollback_result=undone.model_dump(mode="json"),
        )
        return await self._finish(stored, "rolled_back", reason)

    async def _read_back(
        self, stored: StoredIntent, connector: WriteConnector, request: WriteRequest
    ) -> VerifyResult:
        """Connector verify; any failure leaves the phase for a later pass (never re-apply)."""
        try:
            return await connector.verify(request)
        except Exception as exc:
            raise _Halt(await self._release(stored, _reason(exc))) from None

    # -- helpers -----------------------------------------------------------------------------

    @staticmethod
    def _rollback_reason(record: ExecutionRecord) -> str:
        stored = record.details.get("rollback_reason")
        if isinstance(stored, str) and _REASON_RE.fullmatch(stored):
            return stored
        return CANARY_FAILED if record.canary == "failed" else VERIFICATION_FAILED

    @staticmethod
    def _stored_apply(stored: StoredIntent, record: ExecutionRecord) -> ApplyResult | None:
        """The recorded apply result; unreadable is treated as absent (verify discovers)."""
        if record.apply_result is None:
            return None
        try:
            return ApplyResult.model_validate(record.apply_result)
        except ValidationError:
            logger.error(
                "recorded apply result is unreadable; discovering the outcome by verify",
                extra={"event": "action.apply_result_unreadable", "intent_id": stored.intent_id},
            )
            return None

    def _now(self) -> datetime:
        return self._clock()

    async def _leased_call[T](
        self, stored: StoredIntent, call: Callable[[], Awaitable[T]]
    ) -> tuple[StoredIntent, T | Exception]:
        """Run one connector call while a renewal task keeps the lease alive.

        Returns the latest stored intent (renewals move its ETag) and the call's result or the
        ``Exception`` it raised. A lost lease ends the pass ``skipped`` ``lease_lost`` whatever
        the call did: the new owner discovers the outcome by verify, this worker records nothing.
        """
        keeper = _LeaseKeeper(self._renew_lease, stored, interval=self._renewal, sleep=self._sleep)
        keeper.start()
        outcome: T | Exception
        try:
            try:
                outcome = await call()
            except Exception as exc:
                outcome = exc
        finally:
            await keeper.stop()
        if keeper.lost:
            logger.error(
                "lease lost to another executor during a connector call; not finalizing",
                extra={"event": "action.lease_lost", "intent_id": stored.intent_id},
            )
            raise _Halt(self._report(stored.intent_id, "skipped", LEASE_LOST, stored.state))
        return keeper.stored, outcome

    async def _renew_lease(self, stored: StoredIntent) -> StoredIntent:
        """Extend the lease without changing the phase (ETag-conditional, no audit record)."""
        record = stored.execution or ExecutionRecord()
        at = self._now()
        renewed = record.model_copy(
            update={
                "lease_owner": self._worker_id,
                "lease_expires_at": at + self._lease,
                "details": {**record.details, _LEASE_RENEWED_AT: at.isoformat()},
            }
        )
        return await self._service.record_execution(stored, renewed, now=at)

    def _apply_window_open(self, stored: StoredIntent) -> bool:
        """True while ``max(apply_started_at, last renewal) + lease`` is still in the future."""
        record = stored.execution or ExecutionRecord()
        marks = [record.apply_started_at]
        renewed = record.details.get(_LEASE_RENEWED_AT)
        if isinstance(renewed, str):
            with contextlib.suppress(ValueError):
                marks.append(datetime.fromisoformat(renewed))
        known = [m for m in marks if m is not None and m.tzinfo is not None]
        if not known:
            return False
        return max(known) + self._lease > self._now()

    async def _disabled(self, stored: StoredIntent) -> str | None:
        """Reason execution is stopped for the intent's customer, or ``None`` when enabled."""
        try:
            await require_execution_enabled(self._control, stored.customer_id)
        except NeuroSphereError as exc:
            return _reason(exc)
        return None

    async def _save(
        self,
        stored: StoredIntent,
        *,
        audit: Literal["before", "after"] | None = None,
        target_state_digest: str | None = None,
        result: OutcomeResult | None = None,
        verified: bool = False,
        reason: str | None = None,
        details: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> StoredIntent:
        """Persist progress (renewing the lease); a lost race or store outage ends the pass."""
        record = stored.execution or ExecutionRecord()
        update: dict[str, Any] = {
            **fields,
            "lease_owner": self._worker_id,
            "lease_expires_at": self._now() + self._lease,
        }
        if details:
            update["details"] = {**record.details, **details}
        try:
            return await self._service.record_execution(
                stored,
                record.model_copy(update=update),
                audit=audit,
                target_state_digest=target_state_digest,
                result=result,
                verified=verified,
                reason=reason,
                now=self._now(),
            )
        except StaleVersionError as exc:
            raise _Halt(self._report(stored.intent_id, "skipped", _reason(exc))) from None
        except NeuroSphereError as exc:
            # Audit or store outage: the step did not happen; hand the lease back if we can.
            raise _Halt(await self._release(stored, _reason(exc))) from None

    async def _finish(
        self,
        stored: StoredIntent,
        outcome: Literal["succeeded", "failed", "rolled_back"],
        reason: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> ExecutionReport:
        record = stored.execution or ExecutionRecord()
        if details:
            record = record.model_copy(update={"details": {**record.details, **details}})
        try:
            done = await self._service.finish_execution(
                stored, outcome=outcome, reason=reason, execution=record, now=self._now()
            )
        except StaleVersionError as exc:
            return self._report(stored.intent_id, "skipped", _reason(exc))
        except NeuroSphereError as exc:
            return self._report(stored.intent_id, "deferred", _reason(exc))
        status = done.intent.status_reason
        return self._report(stored.intent_id, outcome, status or reason, done.state)

    async def _release(self, stored: StoredIntent, reason: str) -> ExecutionReport:
        """Give the lease back, keep the phase; a later pass resumes. Best effort."""
        record = stored.execution or ExecutionRecord()
        try:
            await self._service.record_execution(
                stored,
                record.model_copy(update={"lease_owner": None, "lease_expires_at": None}),
                now=self._now(),
            )
        except NeuroSphereError:
            pass  # the lease simply lapses
        return self._report(stored.intent_id, "deferred", reason, stored.state)

    async def _after_refusal(self, stored: StoredIntent, exc: NeuroSphereError) -> ExecutionReport:
        """The service refused a recheck: it either failed the intent or changed nothing."""
        try:
            current = await self._service.get(stored.key)
        except (IntentNotFoundError, NeuroSphereError):
            return self._report(stored.intent_id, "deferred", _reason(exc))
        outcome = _FINAL_OUTCOME.get(current.state)
        if outcome is not None:
            return self._report(
                stored.intent_id, outcome, current.intent.status_reason, current.state
            )
        return await self._release(current, _reason(exc))

    def _report(
        self,
        intent_id: str,
        outcome: ReportOutcome,
        reason: str | None = None,
        state: str | None = None,
    ) -> ExecutionReport:
        logger.info(
            "action execution pass",
            extra={
                "event": "action.execution",
                "intent_id": intent_id,
                "outcome": outcome,
                "reason": reason,
            },
        )
        return ExecutionReport(intent_id=intent_id, outcome=outcome, reason=reason, state=state)
