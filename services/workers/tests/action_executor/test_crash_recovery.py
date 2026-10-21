"""Fault injection: a restarted executor resumes through verify and never applies twice."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from neurosphere_core.actions import StoredIntent
from neurosphere_workers.actions import DEFAULT_ACTION_CONNECTORS, ActionExecutorWorker

from .executor_support import (
    FOUNDRY_SWAP_OPS,
    CountingConnector,
    FakeArm,
    Harness,
    SimulatedCrash,
    draft_request,
    foundry_connector,
    phase_is,
)

LEASE_LAPSED = timedelta(minutes=6)


async def crash_then_resume(h: Harness, *, same_worker: bool = False) -> str:
    """Run until the injected crash, then a NEW executor over the same store resumes."""
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    if not same_worker:
        h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-1" if same_worker else "exec-2").execute(key)
    stored = await h.current(key)
    assert stored.execution is not None
    assert stored.execution.attempts == 2
    assert h.connector.count("apply") == 1
    return report.outcome


async def test_crash_after_applying_recorded_before_the_write_is_failed_not_reapplied() -> None:
    h = Harness()
    h.connector.crash_in_apply = "before_write"
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    mid = await h.current(key)
    assert mid.execution is not None
    assert mid.execution.phase == "applying"
    assert mid.execution.apply_may_have_happened()
    h.connector.crash_in_apply = None
    h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-2").execute(key)
    assert (report.outcome, report.reason) == ("failed", "apply_not_observed")
    assert h.connector.count("apply") == 1  # the crashed call only; never re-applied
    assert h.connector.calls[-1] == "verify"
    record = (await h.current(key)).execution
    assert record is not None and record.details["operator_attention"] is True


async def test_crash_mid_apply_after_the_write_is_discovered_by_verify() -> None:
    h = Harness()
    h.connector.crash_in_apply = "after_write"
    assert await crash_then_resume(h) == "succeeded"
    assert h.connector.state["properties"]["model"]["name"] == "gpt-4.1"
    record = h.connector.calls
    assert record == ["dry_run", "apply", "verify", "verify", "verify"]


async def test_crash_after_apply_returned_before_the_result_was_recorded() -> None:
    h = Harness()
    h.store.crash_when = phase_is("applied")
    outcome = await crash_then_resume(h)
    assert outcome == "succeeded"


async def test_crash_after_apply_result_recorded_resumes_at_canary() -> None:
    h = Harness()
    h.store.crash_when = phase_is("applied")
    h.store.crash_after_write = True
    assert await crash_then_resume(h) == "succeeded"
    assert h.connector.calls == ["dry_run", "apply", "verify", "verify"]


@pytest.mark.parametrize(
    "crash_point",
    [phase_is("canary"), phase_is("verifying"), phase_is("verifying", verify_matched=True)],
)
async def test_crash_before_verify_resumes_through_verify(
    crash_point: Callable[[StoredIntent], bool],
) -> None:
    h = Harness()
    h.store.crash_when = crash_point
    assert await crash_then_resume(h) == "succeeded"


async def test_crash_inside_verify_resumes_through_verify() -> None:
    h = Harness()
    h.connector.crash_in_verify = True
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    h.connector.crash_in_verify = False
    h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-2").execute(key)
    assert report.outcome == "succeeded"
    assert h.connector.count("apply") == 1


async def test_crash_after_failed_verify_resumes_with_rollback_not_apply() -> None:
    h = Harness()
    h.connector.apply_noop = True
    h.store.crash_when = phase_is("rolling_back")
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-2").execute(key)
    assert (report.outcome, report.reason) == ("rolled_back", "verification_failed")
    assert h.connector.count("apply") == 1
    assert h.connector.count("rollback") == 1


async def test_crash_after_rollback_recorded_finishes_rolled_back_without_calls() -> None:
    h = Harness()
    h.connector.apply_noop = True
    h.store.crash_when = phase_is("rolling_back", rolled_back=True)
    h.store.crash_after_write = True
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    calls = list(h.connector.calls)
    h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-2").execute(key)
    assert report.outcome == "rolled_back"
    assert h.connector.calls == calls


async def test_live_lease_blocks_another_worker_until_it_lapses() -> None:
    h = Harness()
    h.connector.crash_in_apply = "after_write"
    key = await h.executing()
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1").execute(key)
    calls = list(h.connector.calls)
    blocked = await h.executor("exec-2").execute(key)
    assert (blocked.outcome, blocked.reason) == ("skipped", "execution_leased")
    assert h.connector.calls == calls
    worker = ActionExecutorWorker(h.executor("exec-2"), h.store, clock=h.clock)
    assert await worker.fetch_batch(None) is None  # leased elsewhere: not even fetched
    h.clock.advance(LEASE_LAPSED)
    assert [r.outcome for r in await worker.run_once()] == ["succeeded"]
    assert h.connector.count("apply") == 1


async def test_same_worker_restart_resumes_immediately() -> None:
    h = Harness()
    h.connector.crash_in_apply = "after_write"
    assert await crash_then_resume(h, same_worker=True) == "succeeded"


async def test_transient_verify_failure_after_apply_never_reapplies() -> None:
    from neurosphere_core.errors import DependencyTransientError

    h = Harness()
    key = await h.executing()
    h.connector.verify_error = DependencyTransientError(reason="arm_unreachable")
    first = await h.executor().execute(key)
    assert (first.outcome, first.reason) == ("deferred", "arm_unreachable")
    mid = (await h.current(key)).execution
    assert mid is not None and mid.lease_owner is None and mid.phase == "canary"
    h.connector.verify_error = None
    second = await h.executor().execute(key)
    assert second.outcome == "succeeded"
    assert h.connector.count("apply") == 1


async def test_foundry_crash_after_put_is_discovered_and_not_reapplied() -> None:
    arm = FakeArm()
    h = Harness(connector=CountingConnector(advisory=True))
    h.registry.register(foundry_connector(arm))
    h.store.crash_when = phase_is("applied")
    key = await h.executing(draft_request(operations=FOUNDRY_SWAP_OPS))
    table = dict(DEFAULT_ACTION_CONNECTORS)
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1", table=table).execute(key)
    assert len(arm.puts) == 1
    h.clock.advance(LEASE_LAPSED)
    report = await h.executor("exec-2", table=table).execute(key)
    assert report.outcome == "succeeded"
    assert len(arm.puts) == 1
    record = (await h.current(key)).execution
    assert record is not None
    assert record.details["apply_result_source"] == "verify_discovery"
