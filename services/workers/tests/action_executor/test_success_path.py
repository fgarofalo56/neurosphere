"""Happy path: recheck -> dry_run -> apply -> canary -> verify -> succeeded, from the target."""

from __future__ import annotations

import pytest
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.actions import InMemoryExecutionControl
from neurosphere_workers.actions import (
    DEFAULT_ACTION_CONNECTORS,
    ActionExecutor,
    ActionExecutorWorker,
)

from .executor_support import (
    FAKE_CONNECTOR,
    FOUNDRY_SWAP_OPS,
    CountingConnector,
    FakeArm,
    Harness,
    draft_request,
    foundry_connector,
)


async def test_success_path_applies_once_and_verifies_against_the_target() -> None:
    h = Harness()
    key = await h.executing()
    report = await h.executor().execute(key)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert h.connector.calls == ["dry_run", "apply", "verify", "verify"]
    assert h.connector.state["properties"]["model"]["name"] == "gpt-4.1"
    stored = await h.current(key)
    record = stored.execution
    assert record is not None
    assert record.phase == "done"
    assert record.verify_matched is True
    assert record.canary == "verify_only"
    assert record.rolled_back is False
    assert record.apply_result is not None
    assert record.apply_result["version_after"] == "etag-2"
    assert record.lease_owner is None
    assert record.attempts == 1
    assert record.apply_started_at is not None and record.apply_finished_at is not None
    assert h.final_transition() == ("executing", "succeeded", None)


async def test_dry_run_intent_succeeds_without_apply() -> None:
    h = Harness()
    key = await h.executing(draft_request(dry_run=True))
    report = await h.executor().execute(key)
    assert report.outcome == "succeeded"
    assert h.connector.calls == ["dry_run"]
    assert h.connector.state["properties"]["model"]["name"] == "gpt-4o"


async def test_terminal_intent_is_skipped_without_connector_calls() -> None:
    h = Harness()
    key = await h.executing()
    await h.executor().execute(key)
    calls = list(h.connector.calls)
    again = await h.executor("exec-2").execute(key)
    assert again.outcome == "skipped"
    assert h.connector.calls == calls


@pytest.mark.parametrize(
    ("table", "registered"),
    [
        ({}, True),  # no mapping for the action kind
        ({"model_deployment_swap": "not-registered"}, True),
        ({"model_deployment_swap": FAKE_CONNECTOR}, False),  # registry refused / empty
    ],
)
async def test_unresolvable_target_fails_capability_unavailable_without_calls(
    table: dict[str, str], registered: bool
) -> None:
    h = Harness()
    if not registered:
        h.registry = WriteTargetRegistry()
    key = await h.executing()
    report = await h.executor(table=table).execute(key)
    assert (report.outcome, report.reason) == ("failed", "capability_unavailable")
    assert h.connector.calls == []


async def test_connector_turned_advisory_fails_without_calls() -> None:
    h = Harness()
    key = await h.executing()
    h.connector._advisory = True  # pyright: ignore[reportPrivateUsage]
    report = await h.executor().execute(key)
    assert (report.outcome, report.reason) == ("failed", "capability_unavailable")
    assert h.connector.calls == []


def test_execution_control_is_mandatory() -> None:
    h = Harness()
    with pytest.raises(TypeError):
        ActionExecutor(
            h.service,
            h.registry,
            execution_control=None,  # type: ignore[arg-type]
            worker_id="exec-1",
        )


async def test_worker_claims_executing_intents_and_runs_them() -> None:
    h = Harness()
    first = await h.executing()
    second = await h.executing(draft_request(key="idem-executor-0002"))
    worker = ActionExecutorWorker(h.executor(), h.store, clock=h.clock)
    reports = await worker.run_once()
    assert sorted(r.intent_id for r in reports) == sorted([first.intent_id, second.intent_id])
    # The second intent's dry_run sees the target already changed by the first: stale.
    outcomes = sorted(r.outcome for r in reports)
    assert outcomes == ["failed", "succeeded"]
    assert await worker.run_once() == []
    assert await worker.fetch_batch(None) is None


async def test_success_through_the_foundry_reference_connector() -> None:
    arm = FakeArm()
    h = Harness(connector=CountingConnector(advisory=True))  # not registered
    h.registry.register(foundry_connector(arm))
    key = await h.executing(draft_request(operations=FOUNDRY_SWAP_OPS))
    executor = h.executor(table=dict(DEFAULT_ACTION_CONNECTORS))
    report = await executor.execute(key)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert len(arm.puts) == 1
    assert arm.model() == {"format": "OpenAI", "name": "gpt-4.1", "version": "2025-04-14"}
    stored = await h.current(key)
    assert stored.execution is not None
    assert stored.execution.verify_matched is True
    assert all("fake-token" not in str(r.url) for r in arm.requests)


async def test_kill_switch_of_the_service_is_independent_of_the_executor() -> None:
    """The executor checks its own required control even if the service has none."""
    h = Harness()
    key = await h.executing()
    control = InMemoryExecutionControl()
    await control.set(
        "contoso", disabled=True, reason="incident", changed_by="p-admin", now=h.clock()
    )
    executor = ActionExecutor(
        h.service,
        h.registry,
        execution_control=control,
        worker_id="exec-1",
        action_connectors={"model_deployment_swap": FAKE_CONNECTOR},
        clock=h.clock,
    )
    report = await executor.execute(key)
    assert (report.outcome, report.reason) == ("deferred", "emergency_disabled")
    assert h.connector.calls == []
