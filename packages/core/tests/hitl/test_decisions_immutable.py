"""Decisions are append-only, hash-chained through the PRP-06 audit store, and immutable."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from neurosphere_core.audit import InMemoryAuditStore
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, StaleVersionError
from neurosphere_core.hitl import DecisionLog, DecisionStore, InMemoryDecisionStore, decision_digest
from pydantic import ValidationError

from .hitl_helpers import (
    CHAIN,
    CHECKER,
    CHECKER_ID,
    CONFIRMATION,
    SCOPE_HASH,
    T0,
    THIRD,
    THIRD_ID,
    Harness,
    build,
    open_maker_checker,
)

_REFUSED = ("update", "delete", "replace", "upsert", "patch", "remove")
_REASON = "approved after checking the canary plan"


async def _approve(harness: Harness, item_id: str) -> Any:
    return await harness.service.decide(
        item_id,
        CHECKER_ID,
        CHECKER,
        "approved",
        _REASON,
        CONFIRMATION,
        T0,
        "corr-decide-1",
        scope_hash=SCOPE_HASH,
    )


@pytest.mark.parametrize("name", _REFUSED)
def test_decision_log_refuses_update_and_delete(name: str) -> None:
    log = build().decisions
    with pytest.raises(ForbiddenError) as info:
        getattr(log, name)("any-decision-id", {"decision": "rejected"})
    assert info.value.reason == "decision_append_only"


def test_decision_surfaces_have_no_mutating_method() -> None:
    log_public = {n for n, _ in inspect.getmembers(DecisionLog) if not n.startswith("_")}
    assert log_public == {"append", "get", "list_for_item", *_REFUSED}
    store_public = {n for n in vars(DecisionStore) if not n.startswith("_")}
    assert store_public == {"create", "get", "list_for_item"}


async def test_returned_decision_is_frozen_and_reads_are_copies() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    decision = await _approve(harness, item.item_id)
    with pytest.raises(ValidationError):
        decision.decision = "rejected"
    # Mutating a nested object of a returned copy never reaches the stored record.
    decision.reviewer.principal_pseudonym = "p-forged"
    again = await harness.decisions.get(decision.decision_id.root)
    assert again is not None
    assert again.reviewer.principal_pseudonym == CHECKER.principal_pseudonym
    assert again.decision == "approved"


async def test_decision_is_hash_chained_in_audit_without_its_text() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    decision = await _approve(harness, item.item_id)
    records = await harness.audit.read_range(CHAIN, start=0, limit=500)
    decision_records = [r for r in records if r.operation == "hitl.decision.maker_checker"]
    assert [r.kind for r in decision_records] == ["before", "after"]
    for record in decision_records:
        assert record.subject is not None and record.subject.state_digest is not None
        assert record.subject.state_digest.root == decision_digest(decision)
        assert record.actor == CHECKER
        assert record.intent_id is not None
    after = decision_records[1]
    assert after.outcome is not None
    assert after.outcome.verified is True
    assert after.outcome.detail == "decision=approved"
    dumped = json.dumps([r.model_dump(mode="json") for r in records])
    assert _REASON not in dumped
    assert (await harness.audit.verify(CHAIN)).ok


async def test_failed_audit_write_stores_no_decision() -> None:
    class BrokenAudit(InMemoryAuditStore):
        broken = False

        async def create_record(self, chain_id: str, sequence: int, document: Any) -> None:
            if self.broken:
                raise OSError("audit backend down")
            await super().create_record(chain_id, sequence, document)

    audit_store = BrokenAudit()
    harness = build(audit_store=audit_store)
    item = await open_maker_checker(harness)
    audit_store.broken = True
    with pytest.raises(DependencyTransientError) as info:
        await _approve(harness, item.item_id)
    assert info.value.reason == "audit_write_failed"
    assert await harness.decision_store.list_for_item(item.item_id) == []
    stored = await harness.store.get(item.item_id)
    assert stored is not None and stored.state_name == "pending"


async def test_store_is_create_only() -> None:
    store = InMemoryDecisionStore()
    await store.create("d-1", {"review_item_id": "r-1", "decision": "approved"})
    with pytest.raises(StaleVersionError) as info:
        await store.create("d-1", {"review_item_id": "r-1", "decision": "rejected"})
    assert info.value.reason == "decision_exists"
    assert await store.get("d-1") == {"review_item_id": "r-1", "decision": "approved"}


async def test_correction_is_a_new_record_on_a_new_item() -> None:
    harness = build()
    first = await open_maker_checker(harness)
    original = await _approve(harness, first.item_id)
    # Changed mind: a new review item and a new decision; the original is untouched.
    second = await open_maker_checker(harness)
    correction = await harness.service.decide(
        second.item_id,
        THIRD_ID,
        THIRD,
        "rejected",
        "superseded: rollback window too short",
        CONFIRMATION,
        T0,
        "corr-decide-2",
        scope_hash=SCOPE_HASH,
    )
    assert correction.decision_id != original.decision_id
    kept = await harness.decisions.get(original.decision_id.root)
    assert kept == original
    assert [d.decision for d in await harness.service.decisions(first.item_id)] == ["approved"]
    assert [d.decision for d in await harness.service.decisions(second.item_id)] == ["rejected"]
