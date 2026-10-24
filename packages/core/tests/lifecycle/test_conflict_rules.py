"""Conflict precedence: audit > hold > min retention > subject request > max expiry."""

from __future__ import annotations

from datetime import timedelta

from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LegalHold,
    LifecycleRequest,
    Rule,
    TargetRef,
    governing_rule,
)

from .lifecycle_helpers import NOW, make_ctx, make_rig, record


def _req(action: ActionKind, rid: str = "r1") -> LifecycleRequest:
    return LifecycleRequest(
        action=action,
        target=TargetRef(target_kind="catalog", container="records", record_id=rid),
    )


def _hold(**kw: object) -> LegalHold:
    return LegalHold.model_validate({"reason_code": "litigation", "placed_at": NOW, **kw})


def test_precedence_order_is_total_and_adjacent_pairs_hold() -> None:
    ordered = [
        Rule.AUDIT_IMMUTABILITY,
        Rule.LEGAL_HOLD,
        Rule.MIN_RETENTION,
        Rule.SUBJECT_REQUEST,
        Rule.MAX_RETENTION_EXPIRY,
    ]
    for i, higher in enumerate(ordered):
        for lower in ordered[i + 1 :]:
            assert governing_rule([lower, higher]) is higher
    assert governing_rule([]) is None


async def test_hold_blocks_subject_deletion_and_is_queued_and_audited() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100))
    await rig.holds.place(_hold(record_id="r1"))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.blocked_by is Rule.LEGAL_HOLD
    assert "r1" in rig.target.records
    assert rig.target.delete_calls == 0
    assert len(await rig.queue.pending()) == 1
    kinds = await rig.audit_records()
    assert ("denied", "legal_hold", None) in kinds


async def test_hold_blocks_retention_expiry() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=4000))
    await rig.holds.place(_hold(data_class="telemetry"))
    out = await rig.engine.submit(_req(ActionKind.EXPIRE), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.blocked_by is Rule.LEGAL_HOLD
    assert rig.target.delete_calls == 0


async def test_hold_blocks_pseudonymization_and_subject_erasure() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100, subject_id="subj-1"))
    await rig.holds.place(_hold(subject_id="subj-1"))
    pseud = await rig.engine.submit(_req(ActionKind.PSEUDONYMIZE), make_ctx())
    erase = await rig.engine.submit(
        LifecycleRequest(action=ActionKind.ERASE_SUBJECT, subject_id="subj-1"), make_ctx()
    )
    assert pseud.status is JobStatus.QUEUED
    assert erase.status is JobStatus.QUEUED
    assert await rig.mappings.exists("subj-1")


async def test_queued_request_executes_when_hold_lifts_and_not_before() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100))
    hold = _hold(record_id="r1")
    await rig.holds.place(hold)
    await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert await rig.engine.process_queue() == []  # still held: stays queued
    assert len(await rig.queue.pending()) == 1
    assert await rig.holds.release(hold.hold_id)
    done = await rig.engine.process_queue()
    assert [o.status for o in done] == [JobStatus.COMPLETED]
    assert "r1" not in rig.target.records
    assert await rig.queue.pending() == []


async def test_duplicate_blocked_request_is_not_requeued_or_reaudited() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100))
    await rig.holds.place(_hold(record_id="r1"))
    await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert len(await rig.queue.pending()) == 1
    assert len(await rig.audit_records()) == 1


async def test_min_retention_beats_subject_request_then_releases() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=10))  # min 30 days
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.blocked_by is Rule.MIN_RETENTION
    assert out.not_before == NOW + timedelta(days=20)
    assert "r1" in rig.target.records
    # time passes: a later engine clock lets the queued request through
    rig.engine._clock = lambda: NOW + timedelta(days=21)  # pyright: ignore[reportPrivateUsage]
    done = await rig.engine.process_queue()
    assert [o.effect for o in done] == [Effect.DELETED]
    assert done[0].governing_rule is Rule.SUBJECT_REQUEST


async def test_hold_beats_min_retention_when_both_apply() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=10))
    await rig.holds.place(_hold(record_id="r1"))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.blocked_by is Rule.LEGAL_HOLD


async def test_subject_request_beats_max_expiry_not_due() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=40))  # past min (30), far from max (365)
    expire = await rig.engine.submit(_req(ActionKind.EXPIRE), make_ctx())
    assert expire.status is JobStatus.NOT_DUE
    assert "r1" in rig.target.records
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.status is JobStatus.COMPLETED
    assert out.governing_rule is Rule.SUBJECT_REQUEST


async def test_max_expiry_deletes_when_due_and_verified() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=400))
    out = await rig.engine.submit(_req(ActionKind.EXPIRE), make_ctx())
    assert out.status is JobStatus.COMPLETED
    assert out.governing_rule is Rule.MAX_RETENTION_EXPIRY
    assert out.verified
    assert "r1" not in rig.target.records


async def test_pseudonymization_reports_reidentifiable_via_retained_mapping() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100, subject_id="subj-1"))
    out = await rig.engine.submit(_req(ActionKind.PSEUDONYMIZE), make_ctx())
    assert out.effect is Effect.PSEUDONYMIZED
    assert out.effect is not Effect.DELETED
    assert out.reidentifiable is True
    assert "r1" in rig.target.records  # still present: not a deletion


async def test_erasure_destroys_mapping_and_reports_not_reidentifiable() -> None:
    rig = make_rig()
    out = await rig.engine.submit(
        LifecycleRequest(action=ActionKind.ERASE_SUBJECT, subject_id="subj-1"), make_ctx()
    )
    assert out.effect is Effect.MAPPING_DESTROYED
    assert out.reidentifiable is False
    assert not await rig.mappings.exists("subj-1")
