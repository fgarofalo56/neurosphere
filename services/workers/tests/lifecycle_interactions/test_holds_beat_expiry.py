"""Expiry of ``interaction_content`` through the real engine: holds win, purges are whole."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from neurosphere_core.interactions import DATA_CLASS_INTERACTION, InteractionStoreError
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LegalHold,
    LifecycleRequest,
    Rule,
    TargetRef,
)
from neurosphere_core.lifecycle.models import LifecycleOutcome

from .interaction_rig import (
    CONTAINER,
    CUSTOMER,
    DOMAIN,
    FRESH_NOW,
    SLASH_DOMAIN,
    Rig,
    make_ctx,
    make_rig,
    principal,
)

PLACED = datetime(2026, 11, 21, tzinfo=UTC)


async def _sweep(rig: Rig) -> list[LifecycleOutcome]:
    return await rig.engine.sweep_expiry(
        make_ctx(), target=rig.target, data_class=DATA_CLASS_INTERACTION
    )


def _by_id(outcomes: list[LifecycleOutcome], rig: Rig) -> dict[str, LifecycleOutcome]:
    # sweep_expiry submits in list order, which is record-id order.
    ids = sorted(rig.seeded)
    assert len(ids) == len(outcomes)
    return dict(zip(ids, outcomes, strict=True))


def _assert_held(outcome: LifecycleOutcome) -> None:
    assert outcome.blocked_by is Rule.LEGAL_HOLD
    assert outcome.reason == "legal_hold"
    assert outcome.effect is Effect.NONE


def _assert_purged(rig: Rig, record_id: str, outcome: LifecycleOutcome) -> None:
    assert outcome.status is JobStatus.COMPLETED
    assert outcome.effect is Effect.DELETED
    assert outcome.verified is True
    assert outcome.governing_rule is Rule.MAX_RETENTION_EXPIRY
    assert not rig.has_blob(record_id)
    assert not rig.has_index(record_id)


async def test_a_data_class_hold_keeps_every_expired_interaction(rig: Rig) -> None:
    ids = [await rig.seed(), await rig.seed(domain_id=SLASH_DOMAIN)]
    await rig.holds.place(
        LegalHold(reason_code="litigation", data_class=DATA_CLASS_INTERACTION, placed_at=PLACED)
    )
    outcomes = await _sweep(rig)
    assert len(outcomes) == 2
    for outcome in outcomes:
        _assert_held(outcome)
    for record_id in ids:
        assert rig.has_blob(record_id)
        assert rig.has_index(record_id)


async def test_a_record_hold_keeps_that_record_and_the_rest_expire(rig: Rig) -> None:
    held = await rig.seed()
    free = await rig.seed()
    await rig.holds.place(LegalHold(reason_code="litigation", record_id=held, placed_at=PLACED))
    outcomes = _by_id(await _sweep(rig), rig)
    _assert_held(outcomes[held])
    assert rig.has_blob(held)
    assert rig.has_index(held)
    _assert_purged(rig, free, outcomes[free])


async def test_a_subject_hold_keeps_that_principals_records(rig: Rig) -> None:
    alice, bob = principal("alice"), principal("bob")
    held = await rig.seed(principal_id=alice)
    free = await rig.seed(principal_id=bob)
    await rig.holds.place(LegalHold(reason_code="litigation", subject_id=alice, placed_at=PLACED))
    outcomes = _by_id(await _sweep(rig), rig)
    _assert_held(outcomes[held])
    assert rig.has_blob(held)
    assert rig.has_index(held)
    _assert_purged(rig, free, outcomes[free])


async def test_unheld_expired_records_are_purged_blob_and_index(rig: Rig) -> None:
    ids = [await rig.seed(), await rig.seed(domain_id=SLASH_DOMAIN, principal_id=principal("c"))]
    outcomes = _by_id(await _sweep(rig), rig)
    for record_id in ids:
        _assert_purged(rig, record_id, outcomes[record_id])
    assert rig.content.blobs == {}
    assert rig.index.documents == {}
    assert rig.wrapper.unwrap_calls == 0


async def test_a_released_hold_lets_the_next_run_purge(rig: Rig) -> None:
    record_id = await rig.seed()
    hold = LegalHold(reason_code="litigation", record_id=record_id, placed_at=PLACED)
    await rig.holds.place(hold)
    _assert_held((await _sweep(rig))[0])
    await rig.holds.release(hold.hold_id)
    _assert_purged(rig, record_id, (await _sweep(rig))[0])


async def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, mode="dry_run")
    ids = [await rig.seed(), await rig.seed()]
    outcomes = await _sweep(rig)
    assert [o.reason for o in outcomes] == ["dry_run:would_delete"] * 2
    assert all(o.dry_run and o.effect is Effect.NONE for o in outcomes)
    for record_id in ids:
        assert rig.has_blob(record_id)
        assert rig.has_index(record_id)


async def test_records_inside_retention_are_not_due(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, now=FRESH_NOW)
    record_id = await rig.seed()
    outcomes = await _sweep(rig)
    assert [(o.status, o.reason) for o in outcomes] == [(JobStatus.NOT_DUE, "not_expired")]
    assert rig.has_blob(record_id)
    assert rig.has_index(record_id)


async def test_an_interrupted_purge_reads_as_purged_and_the_next_run_completes_it(
    rig: Rig,
) -> None:
    record_id = await rig.seed()
    stored = rig.seeded[record_id]
    # The first run got as far as the blob delete, then stopped before the index delete.
    del rig.content.blobs[rig.blob_name(record_id)]
    with pytest.raises(InteractionStoreError) as caught:
        await rig.store.read_content(CUSTOMER, DOMAIN, stored.interaction_id.root)
    assert caught.value.reason == "content_purged"
    assert rig.has_index(record_id)
    outcome = (await _sweep(rig))[0]
    assert outcome.effect is Effect.DELETED
    assert outcome.verified is True
    assert not rig.has_index(record_id)
    assert await rig.target.get(record_id) is None


async def test_a_tampered_pointer_never_deletes_another_interactions_blob(rig: Rig) -> None:
    victim = await rig.seed()
    tampered = await rig.seed()
    stored = rig.seeded[tampered]
    key = (CUSTOMER, DOMAIN, stored.interaction_id.root)
    rig.index.documents[key]["content_ref"]["pointer"] = rig.blob_name(victim)
    request = LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="interaction", container=CONTAINER, record_id=tampered),
    )
    outcome = await rig.engine.submit(request, make_ctx())
    assert outcome.effect is Effect.DELETED
    assert not rig.has_index(tampered)
    assert not rig.has_blob(tampered)  # its own (computed) blob went
    assert rig.has_blob(victim)  # the one the pointer named survived
    assert rig.has_index(victim)
