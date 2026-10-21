"""SLA breach escalates (once per deadline), the cap holds, expiry dominates, claims time out."""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.hitl import ReviewItem, apply_timer_action, evaluate_timers
from neurosphere_workers.hitl_timers import HitlTimerWorker
from neurosphere_workers.runtime import Batch, BatchOutcome, InMemoryCheckpointStore, WorkerRunner

from .support import CHECKER, CHECKER_ID, POLICY, T0, FakeClock, Persisted, claim, open_relationship


def _item(**overrides: object) -> ReviewItem:
    data: dict[str, object] = {
        "item_id": "33333333-3333-4333-8333-333333333333",
        "kind": "relationship",
        "state": "pending",
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": "commercial:contoso:catalog:domain:retail",
        "subject_ref": "commercial:contoso:catalog:edge:e-0001",
        "created_at": T0,
        "sla_due_at": T0 + POLICY.sla,
        "expires_at": T0 + POLICY.expiry,
        "policy_version": POLICY.policy_version,
    }
    data.update(overrides)
    return ReviewItem.model_validate(data)


# -- pure evaluation -------------------------------------------------------------------------


def test_nothing_fires_before_the_sla() -> None:
    assert evaluate_timers(_item(), POLICY, T0 + POLICY.sla - timedelta(seconds=1)) == []


def test_sla_breach_escalates_once_and_is_idempotent() -> None:
    item = _item()
    now = T0 + POLICY.sla
    actions = evaluate_timers(item, POLICY, now)
    assert [a.kind for a in actions] == ["escalate"]
    assert actions[0].new_escalation_level == 1
    assert actions[0].deadline == item.sla_due_at
    escalated = apply_timer_action(item, actions[0])
    assert escalated.state_name == "escalated"
    assert escalated.escalation_level == 1
    assert escalated.sla_due_at == now + POLICY.escalation_step
    # Re-evaluating the applied item (same instant, or later but before the next deadline).
    assert evaluate_timers(escalated, POLICY, now) == []
    assert evaluate_timers(escalated, POLICY, now + POLICY.escalation_step / 2) == []
    # Same input, same output: deterministic.
    assert evaluate_timers(item, POLICY, now) == actions


def test_escalation_stops_at_the_cap() -> None:
    item = _item()
    now = T0 + POLICY.sla
    levels: list[int] = []
    for _ in range(POLICY.max_escalations + 3):
        actions = evaluate_timers(item, POLICY, now)
        for action in actions:
            item = apply_timer_action(item, action)
        if item.escalation_level not in levels:
            levels.append(item.escalation_level)
        now += POLICY.escalation_step
    assert levels == [1, 2]
    assert item.escalation_capped is True
    # Once capped, only expiry remains active.
    assert item.active_deadlines() == (item.expires_at,)


def test_expiry_dominates_every_other_deadline() -> None:
    item = _item(
        state="assigned",
        assignee_principal_id=CHECKER_ID,
        assignee=CHECKER,
        assignment_due_at=T0 + timedelta(hours=1),
    )
    actions = evaluate_timers(item, POLICY, T0 + POLICY.expiry)
    assert [a.kind for a in actions] == ["expire"]
    expired = apply_timer_action(item, actions[0])
    assert expired.state_name == "expired"
    assert expired.assignee_principal_id is None
    assert evaluate_timers(expired, POLICY, T0 + POLICY.expiry * 2) == []


def test_assignment_timeout_returns_the_item_to_pending() -> None:
    item = _item(
        state="assigned",
        assignee_principal_id=CHECKER_ID,
        assignee=CHECKER,
        assigned_at=T0,
        assignment_due_at=T0 + POLICY.assignment_timeout,
    )
    actions = evaluate_timers(item, POLICY, T0 + POLICY.assignment_timeout)
    assert [a.kind for a in actions] == ["return_to_pending"]
    released = apply_timer_action(item, actions[0])
    assert released.state_name == "pending"
    assert released.assignee is None and released.assignment_due_at is None
    assert evaluate_timers(released, POLICY, T0 + POLICY.assignment_timeout) == []


@pytest.mark.parametrize("state", ["approved", "rejected", "expired", "executed", "failed"])
def test_final_items_never_fire(state: str) -> None:
    assert evaluate_timers(_item(state=state), POLICY, T0 + POLICY.expiry * 3) == []


# -- worker ----------------------------------------------------------------------------------


async def test_worker_escalates_and_notifies_on_sla_breach() -> None:
    persisted = Persisted()
    clock = FakeClock()
    worker = persisted.worker(clock)
    item = await open_relationship(worker.service)

    assert (await worker.tick()).due == 0
    clock.advance(POLICY.sla)
    report = await worker.tick()
    assert (report.due, report.escalated, report.conflicts) == (1, 1, 0)
    stored = await persisted.store.get(item.item_id)
    assert stored is not None
    assert stored.state_name == "escalated" and stored.escalation_level == 1
    assert await persisted.notifications("review_escalated") == [
        "hitl.notify.email",
        "hitl.notify.teams",
    ]
    # Same clock again: nothing is due, nothing is re-sent.
    assert (await worker.tick()).applied == 0
    assert len(await persisted.notifications("review_escalated")) == 2
    assert await persisted.chain_ok()


async def test_claim_times_out_and_the_assignee_is_told() -> None:
    persisted = Persisted()
    clock = FakeClock()
    worker = persisted.worker(clock)
    item = await open_relationship(worker.service)
    await claim(worker.service, item, clock.now)
    clock.advance(POLICY.assignment_timeout)
    report = await worker.tick()
    assert report.returned_to_pending == 1
    stored = await persisted.store.get(item.item_id)
    assert stored is not None and stored.state_name == "pending"
    assert len(await persisted.notifications("assignment_timed_out")) == 2


async def test_racing_workers_escalate_exactly_once() -> None:
    persisted = Persisted()
    clock = FakeClock()
    first = persisted.worker(clock)
    second = persisted.worker(clock)
    item = await open_relationship(first.service)
    clock.advance(POLICY.sla)
    # Both fetch the same due item before either applies it.
    batch_a = await first.fetch_batch(None)
    batch_b = await second.fetch_batch(None)
    assert batch_a is not None and batch_b is not None
    assert await first.process_batch(batch_a) is BatchOutcome.ACCEPTED
    assert await second.process_batch(batch_b) is BatchOutcome.ACCEPTED
    assert first.last_report is not None and second.last_report is not None
    assert first.last_report.escalated == 1
    assert (second.last_report.escalated, second.last_report.conflicts) == (0, 1)
    stored = await persisted.store.get(item.item_id)
    assert stored is not None and stored.escalation_level == 1
    assert len(await persisted.notifications("review_escalated")) == 2


async def test_runs_under_the_worker_runtime() -> None:
    persisted = Persisted()
    clock = FakeClock()

    class OneShot(HitlTimerWorker):
        runner: WorkerRunner | None = None

        async def process_batch(self, batch: Batch) -> BatchOutcome:
            outcome = await super().process_batch(batch)
            assert self.runner is not None
            self.runner.request_shutdown()
            return outcome

    worker = OneShot(persisted.service(), clock=clock)
    await open_relationship(worker.service)
    clock.advance(POLICY.sla)
    checkpoints = InMemoryCheckpointStore()
    runner = WorkerRunner(worker, checkpoints, idle_seconds=0.01)
    worker.runner = runner
    assert await runner.run(handle_signals=False) == 0
    assert checkpoints.commit_count == 1
    assert worker.last_report is not None and worker.last_report.escalated == 1


async def test_store_outage_surfaces_as_dependency_transient() -> None:
    persisted = Persisted()
    worker = persisted.worker(FakeClock())
    persisted.store.outage = True
    with pytest.raises(DependencyTransientError):
        await worker.tick()


def test_batch_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="batch_limit"):
        HitlTimerWorker(Persisted().service(), batch_limit=0)
