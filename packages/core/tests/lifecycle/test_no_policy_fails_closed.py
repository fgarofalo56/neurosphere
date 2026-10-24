"""Missing or invalid policy: nothing deleted, bodies not retained, engine reports unset."""

from __future__ import annotations

import pytest
from neurosphere_core.lifecycle import (
    UNSET,
    ActionKind,
    JobStatus,
    LifecycleRequest,
    TargetRef,
    load_policy,
)

from .lifecycle_helpers import POLICY_RAW, make_ctx, make_rig, record


def test_missing_and_invalid_policies_load_unset() -> None:
    assert load_policy(None) is UNSET
    assert load_policy({}).status == "unset"
    bad_inverted = {
        **POLICY_RAW,
        "rules": [{"data_class": "telemetry", "min_retention_days": 9, "max_retention_days": 3}],
    }
    no_opt_in = {k: v for k, v in POLICY_RAW.items() if k != "retain_prompt_response_bodies"}
    extra = {**POLICY_RAW, "default_days": 30}
    for raw in (bad_inverted, no_opt_in, extra, {**POLICY_RAW, "rules": []}):
        state = load_policy(raw)
        assert state.status == "unset"
        assert state.problem == "invalid"
        assert not state.bodies_retained


def test_bodies_only_retained_with_explicit_opt_in() -> None:
    assert not load_policy(POLICY_RAW).bodies_retained
    assert load_policy({**POLICY_RAW, "retain_prompt_response_bodies": True}).bodies_retained
    assert not UNSET.bodies_retained


@pytest.mark.parametrize("action", [ActionKind.EXPIRE, ActionKind.DELETE, ActionKind.PSEUDONYMIZE])
async def test_unset_policy_deletes_nothing(action: ActionKind) -> None:
    rig = make_rig(state=UNSET)
    rig.target.put(record("r1", age_days=100000, subject_id="subj-1"))
    out = await rig.engine.submit(
        LifecycleRequest(
            action=action,
            target=TargetRef(target_kind="catalog", container="records", record_id="r1"),
        ),
        make_ctx(),
    )
    assert out.status is JobStatus.QUEUED
    assert out.reason == "policy_unset"
    assert out.policy_status == "unset"
    assert rig.target.delete_calls == 0
    assert rig.target.records["r1"].subject_id == "subj-1"
    assert not rig.engine.bodies_retained


async def test_unset_policy_does_not_erase_mapping_and_sweep_is_noop() -> None:
    rig = make_rig(state=UNSET)
    rig.target.put(record("r1", age_days=100000))
    erase = await rig.engine.submit(
        LifecycleRequest(action=ActionKind.ERASE_SUBJECT, subject_id="subj-1"), make_ctx()
    )
    assert erase.status is JobStatus.QUEUED
    assert await rig.mappings.exists("subj-1")
    assert (
        await rig.engine.sweep_expiry(make_ctx(), target=rig.target, data_class="telemetry") == []
    )
    assert "r1" in rig.target.records


async def test_queued_while_unset_runs_after_policy_is_set() -> None:
    rig = make_rig(state=UNSET)
    rig.target.put(record("r1", age_days=100))
    await rig.engine.submit(
        LifecycleRequest(
            action=ActionKind.DELETE,
            target=TargetRef(target_kind="catalog", container="records", record_id="r1"),
        ),
        make_ctx(),
    )
    rig.engine.set_policy(load_policy(POLICY_RAW))
    done = await rig.engine.process_queue()
    assert [o.status for o in done] == [JobStatus.COMPLETED]


async def test_class_without_rule_fails_closed() -> None:
    rig = make_rig()
    rig.target.put(record("r1", age_days=100000, data_class="unlisted"))
    out = await rig.engine.submit(
        LifecycleRequest(
            action=ActionKind.EXPIRE,
            target=TargetRef(target_kind="catalog", container="records", record_id="r1"),
        ),
        make_ctx(),
    )
    assert out.status is JobStatus.QUEUED
    assert out.reason == "no_rule_for_data_class"
    assert "r1" in rig.target.records
