"""Legal hold (rule 2) outranks subject erasure (rule 4) for any held record of the subject."""

from __future__ import annotations

from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LegalHold,
    LifecycleRequest,
    Rule,
)
from neurosphere_core.lifecycle.adapters import ConversationTarget

from .lifecycle_helpers import CHAIN, NOW, Rig, make_ctx, make_rig, record


def _hold(**kw: object) -> LegalHold:
    return LegalHold.model_validate({"reason_code": "litigation", "placed_at": NOW, **kw})


def _erase(subject: str = "subj-1") -> LifecycleRequest:
    return LifecycleRequest(action=ActionKind.ERASE_SUBJECT, subject_id=subject)


def _rig() -> Rig:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100, subject_id="subj-1", data_class="telemetry"))
    rig.target.put(record("r2", age_days=100, subject_id="subj-2", data_class="billing"))
    return rig


async def _denials(rig: Rig) -> list[str]:
    return [r for kind, r, _ in await rig.audit_records() if kind == "denied" and r is not None]


async def _denied_hold_targets(rig: Rig) -> list[str]:
    out: list[str] = []
    for rec in await rig.audit.read_range(CHAIN, limit=500):
        subject = rec.subject
        if rec.kind == "denied" and subject is not None:
            if subject.target.entity_type == "legal_hold":
                out.append(subject.target.canonical_id.rsplit(":", 1)[1].split("/", 1)[0])
    return out


async def _assert_deferred_then_released(rig: Rig, hold: LegalHold) -> None:
    out = await rig.engine.submit(_erase(), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.blocked_by is Rule.LEGAL_HOLD
    assert await rig.mappings.exists("subj-1")
    denials = await _denials(rig)
    assert denials == ["legal_hold", "legal_hold"]  # the request, then the blocking hold
    assert await _denied_hold_targets(rig) == [hold.hold_id]
    # Resubmitting does not re-audit.
    await rig.engine.submit(_erase(), make_ctx())
    assert await _denials(rig) == denials
    assert await rig.engine.process_queue() == []
    assert await rig.mappings.exists("subj-1")

    assert await rig.holds.release(hold.hold_id)
    done = await rig.engine.process_queue()
    assert [o.status for o in done] == [JobStatus.COMPLETED]
    assert done[0].effect is Effect.MAPPING_DESTROYED
    assert done[0].verified
    assert not await rig.mappings.exists("subj-1")
    assert await rig.queue.pending() == []


async def test_record_level_hold_defers_erasure_until_lifted() -> None:
    rig = _rig()
    hold = _hold(record_id="r1")
    await rig.holds.place(hold)
    await _assert_deferred_then_released(rig, hold)


async def test_target_kind_hold_defers_erasure_until_lifted() -> None:
    rig = _rig()
    hold = _hold(target_kind="catalog")
    await rig.holds.place(hold)
    await _assert_deferred_then_released(rig, hold)


async def test_data_class_hold_defers_erasure_until_lifted() -> None:
    rig = _rig()
    hold = _hold(data_class="telemetry")
    await rig.holds.place(hold)
    await _assert_deferred_then_released(rig, hold)


async def test_subject_named_hold_still_blocks() -> None:
    rig = _rig()
    hold = _hold(subject_id="subj-1")
    await rig.holds.place(hold)
    await _assert_deferred_then_released(rig, hold)


async def test_hold_on_unrelated_subjects_record_does_not_block() -> None:
    rig = _rig()
    await rig.holds.place(_hold(record_id="r2"))
    await rig.holds.place(_hold(data_class="billing"))
    out = await rig.engine.submit(_erase(), make_ctx())
    assert out.status is JobStatus.COMPLETED
    assert out.effect is Effect.MAPPING_DESTROYED
    assert not await rig.mappings.exists("subj-1")


async def test_target_that_cannot_enumerate_defers_with_distinct_reason() -> None:
    rig = _rig()
    rig.target.cannot_enumerate_subjects = True
    await rig.holds.place(_hold(record_id="elsewhere"))
    out = await rig.engine.submit(_erase(), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.reason == "subject_records_unenumerable"
    assert out.blocked_by is Rule.LEGAL_HOLD
    assert await rig.mappings.exists("subj-1")
    assert await _denials(rig) == ["subject_records_unenumerable"]
    # Still unenumerable on retry: stays queued. Once enumerable and unheld, it runs.
    assert await rig.engine.process_queue() == []
    rig.target.cannot_enumerate_subjects = False
    done = await rig.engine.process_queue()
    assert [o.status for o in done] == [JobStatus.COMPLETED]
    assert not await rig.mappings.exists("subj-1")


async def test_conversation_adapter_fails_closed_when_holds_exist() -> None:
    rig = _rig()

    class _Backend:
        async def get(self, owner: str, conversation_id: str, *, now: object) -> None:
            return None

        async def delete(self, owner: str, conversation_id: str) -> bool:
            return False

    rig.registry.register(ConversationTarget("conversations", _Backend()))  # type: ignore[arg-type]
    await rig.holds.place(_hold(record_id="elsewhere"))
    out = await rig.engine.submit(_erase(), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert out.reason == "subject_records_unenumerable"
    assert await rig.mappings.exists("subj-1")
