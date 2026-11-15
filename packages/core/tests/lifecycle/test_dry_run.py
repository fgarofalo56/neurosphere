"""Dry-run is the default: decisions and audit run, no mutating target method is called."""

from __future__ import annotations

import pytest
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LifecycleRequest,
    TargetRef,
)

from .lifecycle_helpers import make_ctx, make_rig, record


def _req(action: ActionKind, rid: str = "r1") -> LifecycleRequest:
    return LifecycleRequest(
        action=action,
        target=TargetRef(target_kind="catalog", container="records", record_id=rid),
    )


def test_engine_defaults_to_dry_run() -> None:
    from neurosphere_core.lifecycle import LifecycleEngine
    from neurosphere_core.lifecycle.memory import (
        InMemoryHoldRegistry,
        InMemoryRequestQueue,
    )
    from neurosphere_core.lifecycle.targets import TargetRegistry

    rig = make_rig()
    engine = LifecycleEngine(
        targets=TargetRegistry(),
        holds=InMemoryHoldRegistry(),
        queue=InMemoryRequestQueue(),
        audit=rig.audit,
        audit_chain_id="c",
        cloud="commercial",
        customer_id="contoso",
    )
    assert engine.mode == "dry_run"


async def test_dry_run_delete_keeps_record_and_audits_would_delete() -> None:
    rig = make_rig(mode="dry_run")
    rig.target.put(record("r1", age_days=100))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.status is JobStatus.COMPLETED
    assert out.dry_run is True
    assert out.effect is Effect.NONE
    assert out.verified is False
    assert out.reason == "dry_run:would_delete"
    assert "r1" in rig.target.records
    assert rig.target.delete_calls == 0
    kinds = await rig.audit_records()
    assert [k for k, _, _ in kinds] == ["before", "after"]
    assert kinds[-1][2] == "dry_run:would_delete"


async def test_dry_run_expire_keeps_record() -> None:
    rig = make_rig(mode="dry_run")
    rig.target.put(record("r1", age_days=1000))
    out = await rig.engine.submit(_req(ActionKind.EXPIRE), make_ctx())
    assert out.dry_run is True
    assert out.effect is Effect.NONE
    assert "r1" in rig.target.records
    assert rig.target.delete_calls == 0


async def test_dry_run_pseudonymize_keeps_subject() -> None:
    rig = make_rig(mode="dry_run")
    rig.target.put(record("r1", age_days=100, subject_id="subj-1"))
    out = await rig.engine.submit(_req(ActionKind.PSEUDONYMIZE), make_ctx())
    assert out.dry_run is True
    assert out.effect is Effect.NONE
    assert out.reason == "dry_run:would_pseudonymize"
    assert rig.target.records["r1"].subject_id == "subj-1"
    assert rig.target.records["r1"].pseudonymized is False


async def test_dry_run_erase_keeps_mapping() -> None:
    rig = make_rig(mode="dry_run")
    out = await rig.engine.submit(
        LifecycleRequest(action=ActionKind.ERASE_SUBJECT, subject_id="subj-1"), make_ctx()
    )
    assert out.dry_run is True
    assert out.effect is Effect.NONE
    assert out.reason == "dry_run:would_erase"
    assert await rig.mappings.exists("subj-1") is True
    assert (await rig.audit_records())[-1][2] == "dry_run:would_erase"


async def test_execute_mode_mutates_and_is_not_marked_dry() -> None:
    rig = make_rig(mode="execute")
    rig.target.put(record("r1", age_days=100))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx())
    assert out.dry_run is False
    assert out.effect is Effect.DELETED
    assert out.verified is True
    assert "r1" not in rig.target.records


async def test_job_can_request_dry_run_in_execute_mode() -> None:
    rig = make_rig(mode="execute")
    rig.target.put(record("r1", age_days=100))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx(), dry_run=True)
    assert out.dry_run is True
    assert "r1" in rig.target.records


async def test_job_cannot_override_dry_run_mode() -> None:
    rig = make_rig(mode="dry_run")
    rig.target.put(record("r1", age_days=100))
    out = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx(), dry_run=False)
    assert out.dry_run is True
    assert "r1" in rig.target.records


@pytest.mark.parametrize("mode", ["dry_run", "execute"])
async def test_missing_policy_still_deletes_nothing(mode: str) -> None:
    from neurosphere_core.lifecycle import UNSET

    rig = make_rig(mode=mode, state=UNSET)  # type: ignore[arg-type]
    rig.target.put(record("r1", age_days=1000))
    out = await rig.engine.submit(_req(ActionKind.EXPIRE), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert "r1" in rig.target.records


async def test_queued_dry_run_stays_dry_after_the_hold_lifts() -> None:
    from neurosphere_core.lifecycle import LegalHold

    from .lifecycle_helpers import NOW

    rig = make_rig(mode="execute")
    rig.target.put(record("r1", age_days=100))
    hold = LegalHold.model_validate(
        {"reason_code": "litigation", "placed_at": NOW, "record_id": "r1"}
    )
    await rig.holds.place(hold)
    queued = await rig.engine.submit(_req(ActionKind.DELETE), make_ctx(), dry_run=True)
    assert queued.status is JobStatus.QUEUED
    await rig.holds.release(hold.hold_id)
    results = await rig.engine.process_queue()
    assert [r.dry_run for r in results] == [True]
    assert "r1" in rig.target.records
