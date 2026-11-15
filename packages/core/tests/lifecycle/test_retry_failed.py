"""A FAILED queued outcome is retried with backoff, then audited as failed_final and dropped."""

from __future__ import annotations

from datetime import datetime, timedelta

from neurosphere_core.lifecycle import (
    ActionKind,
    JobStatus,
    LegalHold,
    LifecycleRequest,
    TargetRef,
)

from .lifecycle_helpers import NOW, make_ctx, make_rig, record


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _req() -> LifecycleRequest:
    return LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="catalog", container="records", record_id="r1"),
    )


async def _queued_behind_hold(max_attempts: int = 3, clock: _Clock | None = None):  # type: ignore[no-untyped-def]
    clock = clock or _Clock()
    rig = make_rig(max_attempts=max_attempts, clock=clock)
    rig.target.put(record("r1", age_days=100))
    hold = LegalHold.model_validate(
        {"reason_code": "litigation", "placed_at": NOW, "record_id": "r1"}
    )
    await rig.holds.place(hold)
    await rig.engine.submit(_req(), make_ctx())
    await rig.holds.release(hold.hold_id)
    rig.target.ignore_deletes = True  # the store acknowledges but keeps the record: FAILED
    return rig, clock


async def test_failed_outcome_stays_queued_with_attempts_and_backoff() -> None:
    rig, clock = await _queued_behind_hold()
    assert await rig.engine.process_queue() == []
    (item,) = await rig.queue.pending()
    assert item.attempts == 1
    assert item.not_before == NOW + timedelta(seconds=60)
    # Still backing off: nothing runs and the target is not touched again.
    calls = rig.target.delete_calls
    assert await rig.engine.process_queue() == []
    assert rig.target.delete_calls == calls
    # Past the backoff it is retried and the delay doubles.
    clock.now = NOW + timedelta(seconds=61)
    assert await rig.engine.process_queue() == []
    (item,) = await rig.queue.pending()
    assert item.attempts == 2
    assert item.not_before == clock.now + timedelta(seconds=120)


async def test_retry_succeeds_when_the_store_recovers() -> None:
    rig, clock = await _queued_behind_hold()
    assert await rig.engine.process_queue() == []
    rig.target.ignore_deletes = False
    clock.now = NOW + timedelta(seconds=61)
    results = await rig.engine.process_queue()
    assert [r.status for r in results] == [JobStatus.COMPLETED]
    assert "r1" not in rig.target.records
    assert await rig.queue.pending() == []


async def test_after_max_attempts_it_is_audited_failed_final_and_removed() -> None:
    rig, clock = await _queued_behind_hold(max_attempts=3)
    finals = []
    for step in range(10):
        clock.now = NOW + timedelta(hours=2 * (step + 1))
        finals += await rig.engine.process_queue()
        if not await rig.queue.pending():
            break
    assert [f.reason for f in finals] == ["failed_final"]
    assert finals[0].status is JobStatus.FAILED
    assert await rig.queue.pending() == []
    details = [d for _, _, d in await rig.audit_records()]
    assert details.count("failed_final") == 1
    assert "r1" in rig.target.records  # nothing was ever deleted
