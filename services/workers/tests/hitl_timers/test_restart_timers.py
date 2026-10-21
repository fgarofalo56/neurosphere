"""Timers survive a worker restart: state comes only from the stored deadlines."""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.hitl import InMemoryHitlStore, ReviewItem

from .support import POLICY, FakeClock, Persisted, claim, open_relationship


class FlakyStore(InMemoryHitlStore):
    """Fails the Nth replace with a transient error (a crash or outage mid-batch)."""

    def __init__(self, fail_on: int) -> None:
        super().__init__()
        self.fail_on = fail_on
        self.attempts = 0

    async def replace(self, item: ReviewItem, *, if_match: str) -> ReviewItem:
        self.attempts += 1
        if self.attempts == self.fail_on:
            raise DependencyTransientError("store blip", reason="hitl_store_unavailable")
        return await super().replace(item, if_match=if_match)


async def test_escalation_happens_exactly_once_across_restarts() -> None:
    persisted = Persisted()
    clock = FakeClock()

    worker = persisted.worker(clock)
    item = await open_relationship(worker.service, clock.now)
    clock.advance(POLICY.sla - timedelta(minutes=1))
    assert (await worker.tick()).applied == 0
    del worker  # the process goes away; only the stores remain

    clock.advance(timedelta(minutes=1))
    restarted = persisted.worker(clock)
    assert (await restarted.tick()).escalated == 1
    del restarted

    # A third process at the same instant and shortly after: nothing new is due.
    again = persisted.worker(clock)
    assert (await again.tick()).applied == 0
    clock.advance(POLICY.escalation_step - timedelta(seconds=1))
    assert (await again.tick()).applied == 0

    stored = await persisted.store.get(item.item_id)
    assert stored is not None
    assert stored.state_name == "escalated"
    assert stored.escalation_level == 1
    assert len(await persisted.notifications("review_escalated")) == 2  # email + teams, once
    assert await persisted.chain_ok()


async def test_next_escalation_deadline_is_persisted_not_remembered() -> None:
    persisted = Persisted()
    clock = FakeClock()
    item = await open_relationship(persisted.service(), clock.now)
    clock.advance(POLICY.sla)
    assert (await persisted.worker(clock).tick()).escalated == 1
    clock.advance(POLICY.escalation_step)
    assert (await persisted.worker(clock).tick()).escalated == 1
    clock.advance(POLICY.escalation_step)
    report = await persisted.worker(clock).tick()
    assert (report.escalated, report.capped) == (0, 1)
    clock.advance(POLICY.escalation_step)
    assert (await persisted.worker(clock).tick()).applied == 0
    stored = await persisted.store.get(item.item_id)
    assert stored is not None
    assert stored.escalation_level == POLICY.max_escalations
    assert stored.escalation_capped is True
    clock.now = stored.expires_at
    assert (await persisted.worker(clock).tick()).expired == 1
    final = await persisted.store.get(item.item_id)
    assert final is not None and final.state_name == "expired"


async def test_assignment_deadline_survives_restart() -> None:
    persisted = Persisted()
    clock = FakeClock()
    service = persisted.service()
    item = await open_relationship(service, clock.now)
    await claim(service, item, clock.now)
    del service
    clock.advance(POLICY.assignment_timeout)
    assert (await persisted.worker(clock).tick()).returned_to_pending == 1
    assert (await persisted.worker(clock).tick()).applied == 0
    stored = await persisted.store.get(item.item_id)
    assert stored is not None and stored.state_name == "pending"


async def test_crash_mid_batch_never_double_applies() -> None:
    persisted = Persisted(store=FlakyStore(fail_on=2))
    clock = FakeClock()
    service = persisted.service()
    first = await open_relationship(service, clock.now)
    second = await open_relationship(service, clock.now + timedelta(seconds=1))
    clock.advance(POLICY.sla + timedelta(seconds=1))

    with pytest.raises(DependencyTransientError):
        await persisted.worker(clock).tick()
    applied = await persisted.store.get(first.item_id)
    pending = await persisted.store.get(second.item_id)
    assert applied is not None and applied.escalation_level == 1
    assert pending is not None and pending.escalation_level == 0

    report = await persisted.worker(clock).tick()
    assert (report.due, report.escalated) == (1, 1)
    for item_id in (first.item_id, second.item_id):
        stored = await persisted.store.get(item_id)
        assert stored is not None and stored.escalation_level == 1
    assert len(await persisted.notifications("review_escalated")) == 4  # 2 items x 2 channels
