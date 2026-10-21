"""Emergency disable: no connector calls, intent intact, clean resume; outage = disabled."""

from __future__ import annotations

import pytest
from neurosphere_connector.write import DryRunResult, WriteRequest
from neurosphere_core.actions import IntentKey
from neurosphere_workers.actions import ActionExecutorWorker

from .executor_support import CUSTOMER, CountingConnector, Harness, SimulatedCrash, phase_is


async def disable(h: Harness) -> None:
    await h.control.set(
        CUSTOMER, disabled=True, reason="incident_response", changed_by="p-admin01", now=h.clock()
    )


async def enable(h: Harness) -> None:
    await h.control.set(
        CUSTOMER, disabled=False, reason=None, changed_by="p-admin01", now=h.clock()
    )


async def assert_intact(h: Harness, key: IntentKey, phase: str = "pending") -> None:
    stored = await h.current(key)
    assert stored.state == "executing"
    record = stored.execution
    assert record is not None
    assert record.phase == phase
    assert record.lease_owner is None
    assert record.lease_expires_at is None


async def test_disabled_stops_execution_before_any_connector_call() -> None:
    h = Harness()
    key = await h.executing()
    await disable(h)
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason, report.state) == (
        "deferred",
        "emergency_disabled",
        "executing",
    )
    assert h.connector.calls == []
    await assert_intact(h, key)
    assert (await h.current(key)).execution.attempts == 0  # type: ignore[union-attr]
    await enable(h)
    resumed = await h.executor().execute(key)
    assert resumed.outcome == "succeeded"
    assert h.connector.count("apply") == 1


@pytest.mark.parametrize("error", [RuntimeError("cosmos down"), ConnectionError("reset")])
async def test_control_store_outage_is_treated_as_disabled(error: Exception) -> None:
    h = Harness()
    key = await h.executing()
    h.control.fail_with(error)
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("deferred", "execution_control_unavailable")
    assert h.connector.calls == []
    await assert_intact(h, key)
    h.control.fail_with(None)
    assert (await h.executor().execute(key)).outcome == "succeeded"


class DisablesDuringDryRun(CountingConnector):
    """Flips the kill switch while the dry run is in flight (an operator hits stop)."""

    def __init__(self) -> None:
        super().__init__()
        self.harness: Harness | None = None

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        result = await super().dry_run(request)
        if self.harness is not None and self.count("dry_run") == 1:
            await disable(self.harness)
        return result


async def test_disable_between_dry_run_and_apply_stops_before_apply() -> None:
    connector = DisablesDuringDryRun()
    h = Harness(connector=connector)
    connector.harness = h
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("deferred", "emergency_disabled")
    assert connector.calls == ["dry_run"]
    await assert_intact(h, key, phase="dry_run_done")
    await enable(h)
    resumed = await h.executor().execute(key)
    assert resumed.outcome == "succeeded"
    assert connector.calls == ["dry_run", "dry_run", "apply", "verify", "verify"]


async def test_disabled_during_recovery_makes_no_calls_and_resumes_via_verify() -> None:
    h = Harness()
    h.store.crash_when = phase_is("applied")
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    calls = list(h.connector.calls)
    await disable(h)
    blocked = await h.executor("exec-1").execute(key)
    assert (blocked.outcome, blocked.reason) == ("deferred", "emergency_disabled")
    assert h.connector.calls == calls
    await enable(h)
    resumed = await h.executor("exec-1").execute(key)
    assert resumed.outcome == "succeeded"
    assert h.connector.count("apply") == 1


async def test_worker_pass_while_disabled_changes_nothing() -> None:
    h = Harness()
    keys = [await h.executing()]
    await disable(h)
    worker = ActionExecutorWorker(h.executor(), h.store, clock=h.clock)
    reports = await worker.run_once()
    assert [(r.outcome, r.reason) for r in reports] == [("deferred", "emergency_disabled")]
    assert h.connector.calls == []
    for key in keys:
        await assert_intact(h, key)
    await enable(h)
    assert [r.outcome for r in await worker.run_once()] == ["succeeded"]
