"""Review-reconcile sweep (PRP-17 audit close-out).

Closes maker-checker review items the completion hook could not: terminal intents whose item is
still ``approved``, intents that ended outside the executor, and orphan items left when
``link_review_item`` failed after ``open_item``. Real ``ActionService`` + ``HitlService`` over the
in-memory stores; the counting connector proves the sweep never reaches a target.
"""

from __future__ import annotations

import ast
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.actions import ActionCaller, IntentKey, StoredIntent
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewItem,
    ReviewPolicyRegistry,
)
from neurosphere_workers.actions import (
    RECONCILE_OPERATION,
    ActionExecutor,
    ReviewReconcileWorker,
)
from neurosphere_workers.actions import reconcile as reconcile_module
from neurosphere_workers.runtime import Batch

from .executor_support import CUSTOMER, DOMAIN, TARGET_ID, Harness, draft_request, maker

APPROVER_ID = "commercial:contoso:entra:person:p-checker00000001"
APPROVER = Actor(principal_pseudonym="p-checker1", principal_kind="user", on_behalf_of=None)
SCOPE_HASH = "sha256:" + "b" * 64
GRACE = timedelta(minutes=5)


class AllowAll:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return True


def approver() -> ActionCaller:
    return ActionCaller.model_validate(
        {
            "principal_id": APPROVER_ID,
            "actor": APPROVER.model_dump(mode="json"),
            "scope_hash": SCOPE_HASH,
            "correlation_id": "corr-reconcile-02",
            "channel": "rest",
        }
    )


@dataclass
class Rig:
    """Action plane + HITL over shared in-memory stores, and a sweep factory."""

    h: Harness = field(default_factory=Harness)
    items: InMemoryHitlStore = field(default_factory=InMemoryHitlStore)
    hitl: HitlService = field(init=False)
    _keys: int = 0

    def __post_init__(self) -> None:
        audit = AuditRepository(InMemoryAuditStore())
        self.hitl = HitlService(
            self.items,
            DecisionLog(audit, InMemoryDecisionStore()),
            audit,
            ReviewPolicyRegistry(),
            AllowAll(),
        )
        self.h.rechecker.grant(APPROVER_ID, CUSTOMER, DOMAIN, "action.approve")

    def sweep(self, **options: object) -> ReviewReconcileWorker:
        return ReviewReconcileWorker(
            self.hitl,
            self.h.service,
            auditor=self.h.auditor,
            clock=self.h.clock,
            orphan_grace=GRACE,
            **options,  # type: ignore[arg-type]
        )

    def executor(self) -> ActionExecutor:
        return self.h.executor()  # no completion hook: the gap the sweep closes

    async def awaiting(self) -> StoredIntent:
        """Draft -> ... -> ``awaiting_approval`` (no review item yet)."""
        from neurosphere_contracts.actions.v1.action_intent import PrerequisiteResult

        self._keys += 1
        who = maker()
        drafted = await self.h.service.draft(
            who,
            draft_request(key=f"idem-reconcile-{self._keys:04d}"),
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
        )
        check = PrerequisiteResult.model_validate(
            {
                "check_id": "actor_permission",
                "status": "passed",
                "detail": None,
                "evaluated_at": "2026-10-20T12:00:00Z",
                "evidence_ids": [],
            }
        )
        validated = await self.h.service.record_validation(drafted.stored.key, who, [check])
        presented = await self.h.service.present_confirmation(validated.key, who)
        bound = presented.intent.confirmation_hash
        assert bound is not None
        waiting = await self.h.service.confirm(
            presented.key,
            who,
            confirmation_hash=bound.root,
            current_target_version=presented.intent.target_version,
            requires_approval=True,
            advisory=False,
        )
        assert waiting.state == "awaiting_approval"
        return waiting

    async def open_item(self, stored: StoredIntent, *, intent_id: str | None = None) -> ReviewItem:
        bound = stored.intent.confirmation_hash
        assert bound is not None
        return await self.hitl.open_item(
            kind="maker_checker",
            customer_id=stored.customer_id,
            domain_id=stored.domain_id,
            subject_ref=TARGET_ID,
            now=self.h.clock(),
            correlation_id="corr-reconcile-01",
            action_kind=stored.intent.action_kind,
            intent_id=intent_id or stored.intent_id,
            confirmation_hash=bound.root,
            maker_principal_id=stored.principal_id,
            maker=stored.intent.actor,
        )

    async def linked(self) -> tuple[StoredIntent, ReviewItem]:
        """``awaiting_approval`` intent with its review item opened AND linked (the happy path)."""
        stored = await self.awaiting()
        item = await self.open_item(stored)
        stored = await self.h.service.link_review_item(stored.key, item.item_id)
        return stored, item

    async def approved_and_executed(self, *, noop_apply: bool = False) -> tuple[IntentKey, str]:
        """Approved through HITL + ActionService, then executed WITHOUT the completion hook."""
        stored, item = await self.linked()
        bound = stored.intent.confirmation_hash
        assert bound is not None
        await self.hitl.decide(
            item.item_id,
            APPROVER_ID,
            APPROVER,
            "approved",
            "looks right",
            bound.root,
            self.h.clock(),
            "corr-reconcile-03",
            scope_hash=SCOPE_HASH,
        )
        running = await self.h.service.apply_approval(
            stored.key,
            approver(),
            approved=True,
            approved_confirmation_hash=bound.root,
            current_target_version=stored.intent.target_version,
        )
        assert running.state == "executing"
        self.h.connector.apply_noop = noop_apply
        await self.executor().execute(stored.key)
        return stored.key, item.item_id

    async def state_of(self, item_id: str) -> str:
        found = await self.hitl.get(item_id)
        assert found is not None
        return found.state_name

    def reconcile_events(self) -> list[tuple[str, str | None, str | None]]:
        return [
            (e.kind, e.from_state, e.to_state)
            for e in self.h.auditor.events
            if e.operation == RECONCILE_OPERATION
        ]


# -- gap 1: terminal intents whose item is still open --------------------------------------------


async def test_succeeded_intent_with_approved_item_is_completed_once() -> None:
    rig = Rig()
    key, item_id = await rig.approved_and_executed()
    assert (await rig.h.current(key)).state == "succeeded"
    assert await rig.state_of(item_id) == "approved"  # the gap: no hook ran
    sweep = rig.sweep()
    first = await sweep.run_once()
    assert first.outcomes == ((item_id, "executed"),)
    assert await rig.state_of(item_id) == "executed"
    # Idempotent: a second pass changes nothing and writes nothing.
    replaces, events = rig.items.replace_count, len(rig.h.auditor.events)
    second = await sweep.run_once()
    assert second.changed == 0
    assert rig.items.replace_count == replaces
    assert len(rig.h.auditor.events) == events
    # A fresh worker (process restart) over the same stores is a no-op too.
    assert (await rig.sweep().run_once()).changed == 0
    assert await rig.state_of(item_id) == "executed"


async def test_rolled_back_intent_marks_the_approved_item_failed() -> None:
    rig = Rig()
    key, item_id = await rig.approved_and_executed(noop_apply=True)
    assert (await rig.h.current(key)).state == "rolled_back"
    report = await rig.sweep().run_once()
    assert report.outcomes == ((item_id, "failed"),)
    assert await rig.state_of(item_id) == "failed"


async def test_intent_expired_outside_the_executor_closes_its_review_item() -> None:
    rig = Rig()
    stored, item = await rig.linked()
    rig.h.clock.advance(timedelta(minutes=16))  # past the confirmation expiry
    expired = await rig.h.service.expire_due(now=rig.h.clock())
    assert [s.intent_id for s in expired] == [stored.intent_id]
    assert await rig.state_of(item.item_id) == "pending"
    report = await rig.sweep().run_once()
    assert report.outcomes == ((item.item_id, "expired"),)
    assert await rig.state_of(item.item_id) == "expired"
    assert rig.reconcile_events() == [
        ("before", "pending", "expired"),
        ("after", "pending", "expired"),
    ]


async def test_live_intents_and_their_linked_items_are_untouched() -> None:
    rig = Rig()
    _, pending = await rig.linked()
    rig.h.clock.advance(GRACE * 2)
    report = await rig.sweep().run_once()
    assert report.outcomes == ((pending.item_id, "noop"),)
    assert await rig.state_of(pending.item_id) == "pending"
    assert rig.reconcile_events() == []


# -- gap 2: orphan review items -------------------------------------------------------------------


async def test_orphan_of_an_unlinked_intent_is_relinked_and_a_linked_item_untouched() -> None:
    rig = Rig()
    _, legit = await rig.linked()
    stored = await rig.awaiting()
    orphan = await rig.open_item(stored)  # link_review_item "failed": never called
    rig.h.clock.advance(GRACE + timedelta(seconds=1))
    report = await rig.sweep().run_once()
    assert dict(report.outcomes) == {legit.item_id: "noop", orphan.item_id: "relinked"}
    assert (await rig.h.current(stored.key)).review_item_id == orphan.item_id
    assert await rig.state_of(orphan.item_id) == "pending"  # still reviewable
    assert await rig.state_of(legit.item_id) == "pending"
    # Second pass: both are now properly linked.
    assert (await rig.sweep().run_once()).changed == 0


async def test_duplicate_orphan_is_closed_and_the_linked_item_kept() -> None:
    rig = Rig()
    stored, linked = await rig.linked()
    duplicate = await rig.open_item(stored)  # e.g. a retried open whose link lost
    rig.h.clock.advance(GRACE + timedelta(seconds=1))
    report = await rig.sweep().run_once()
    assert dict(report.outcomes) == {linked.item_id: "noop", duplicate.item_id: "expired"}
    assert await rig.state_of(duplicate.item_id) == "expired"
    assert await rig.state_of(linked.item_id) == "pending"
    assert (await rig.h.current(stored.key)).review_item_id == linked.item_id


async def test_orphan_whose_intent_does_not_exist_is_closed() -> None:
    rig = Rig()
    stored = await rig.awaiting()
    ghost = await rig.open_item(stored, intent_id=str(uuid.uuid4()))
    rig.h.clock.advance(GRACE + timedelta(seconds=1))
    report = await rig.sweep().run_once()
    assert dict(report.outcomes)[ghost.item_id] == "expired"
    events = [e for e in rig.h.auditor.events if e.operation == RECONCILE_OPERATION]
    assert {e.target.entity_type for e in events} == {"review_item"}
    assert {e.intent_id for e in events} == {ghost.intent_id}


async def test_young_orphan_is_left_for_the_in_flight_link() -> None:
    rig = Rig()
    stored = await rig.awaiting()
    orphan = await rig.open_item(stored)
    report = await rig.sweep().run_once()
    assert report.outcomes == ((orphan.item_id, "grace"),)
    assert (await rig.h.current(stored.key)).review_item_id is None
    assert rig.reconcile_events() == []


# -- failure handling ----------------------------------------------------------------------------


async def test_review_store_outage_is_an_idle_tick_and_the_next_sweep_succeeds() -> None:
    rig = Rig()
    _, item_id = await rig.approved_and_executed()
    sweep = rig.sweep()
    rig.items.outage = True
    report = await sweep.run_once()  # no exception escapes
    assert report.scan_failed and report.outcomes == ()
    assert await sweep.fetch_batch(None) is None  # the runner sees an idle tick, not a crash
    rig.items.outage = False
    assert await rig.state_of(item_id) == "approved"
    assert (await sweep.run_once()).outcomes == ((item_id, "executed"),)


async def test_intent_store_outage_mid_sweep_skips_without_change_then_recovers() -> None:
    rig = Rig()
    _, item_id = await rig.approved_and_executed()
    sweep = rig.sweep()
    rig.h.store.inner.fail_with(
        DependencyTransientError("intent store down", reason="intent_store_unavailable")
    )
    report = await sweep.run_once()
    assert report.outcomes == ((item_id, "error"),)
    assert await rig.state_of(item_id) == "approved"
    assert rig.reconcile_events() == []
    rig.h.store.inner.fail_with(None)
    assert (await sweep.run_once()).outcomes == ((item_id, "executed"),)


async def test_audit_outage_fails_closed_and_changes_nothing() -> None:
    rig = Rig()
    _, item_id = await rig.approved_and_executed()
    rig.h.auditor.fail_with(DependencyTransientError("audit down", reason="audit_write_failed"))
    report = await rig.sweep().run_once()
    assert report.outcomes == ((item_id, "error"),)
    assert await rig.state_of(item_id) == "approved"
    rig.h.auditor.fail_with(None)
    assert (await rig.sweep().run_once()).outcomes == ((item_id, "executed"),)


async def test_one_malformed_document_does_not_abort_the_sweep() -> None:
    rig = Rig()
    _, item_id = await rig.approved_and_executed()
    bad_id = "00000000-0000-4000-8000-00000000bad1"
    # Readable query fields, but the document fails ReviewItem validation (no maker fields).
    rig.items._items[bad_id] = json.dumps(  # pyright: ignore[reportPrivateUsage]
        {
            "item_id": bad_id,
            "kind": "maker_checker",
            "state": "approved",
            "customer_id": CUSTOMER,
            "created_at": "2026-10-20T11:00:00Z",
        }
    )
    report = await rig.sweep().run_once()
    assert dict(report.outcomes) == {bad_id: "error", item_id: "executed"}
    assert report.outcomes[0] == (bad_id, "error")  # older, so scanned first
    assert await rig.state_of(item_id) == "executed"


# -- audit and the single write path ---------------------------------------------------------------


async def test_every_reconcile_action_is_audited_and_no_connector_is_called() -> None:
    rig = Rig()
    _, done = await rig.approved_and_executed()
    rig.h.clock.advance(timedelta(seconds=1))  # scan order is creation order
    stored = await rig.awaiting()
    orphan = await rig.open_item(stored)
    rig.h.clock.advance(GRACE + timedelta(seconds=1))
    calls = list(rig.h.connector.calls)
    report = await rig.sweep().run_once()
    assert dict(report.outcomes) == {done: "executed", orphan.item_id: "relinked"}
    assert rig.h.connector.calls == calls  # the sweep never reaches a target
    events = [e for e in rig.h.auditor.events if e.operation == RECONCILE_OPERATION]
    assert [(e.kind, e.result) for e in events] == [
        ("before", None),
        ("after", "succeeded"),
        ("before", None),
        ("after", "succeeded"),
    ]
    assert {e.channel for e in events} == {"worker"}
    assert {(e.customer_id, e.domain_id) for e in events} == {(CUSTOMER, DOMAIN)}
    assert [e.reason for e in events if e.kind == "after"] == [
        "mark_executed.intent_succeeded",
        "relink.orphan_unlinked_intent",
    ]


def test_reconcile_module_never_calls_apply_or_rollback_or_imports_a_connector() -> None:
    source = Path(reconcile_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"apply", "rollback", "verify", "dry_run"}
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("neurosphere_connector")
            assert "executor" not in node.module


# -- runner surface -------------------------------------------------------------------------------


async def test_customer_scope_skips_other_customers() -> None:
    rig = Rig()
    _, item_id = await rig.approved_and_executed()
    other = rig.sweep(customer_id="fabrikam")
    assert (await other.run_once()).outcomes == ()
    assert await rig.state_of(item_id) == "approved"


async def test_batches_are_bounded_and_the_pass_is_gated_by_the_interval() -> None:
    rig = Rig()
    _, first = await rig.approved_and_executed()
    rig.h.clock.advance(timedelta(seconds=1))  # scan order is creation order
    second_stored, second = await rig.linked()
    rig.h.clock.advance(timedelta(minutes=16))
    await rig.h.service.expire_due(now=rig.h.clock())
    sweep = rig.sweep(batch_limit=1, pass_interval=timedelta(minutes=10))
    batch = await sweep.fetch_batch(None)
    assert isinstance(batch, Batch) and batch.items == (first,) and batch.checkpoint
    await sweep.process_batch(batch)
    batch = await sweep.fetch_batch(batch.checkpoint)
    assert isinstance(batch, Batch) and batch.items == (second.item_id,)
    await sweep.process_batch(batch)
    wrap = await sweep.fetch_batch(batch.checkpoint)
    assert isinstance(wrap, Batch) and wrap.items == () and wrap.checkpoint == ""
    # A complete pass is not restarted before the interval elapses.
    assert await sweep.fetch_batch(None) is None
    rig.h.clock.advance(timedelta(minutes=11))
    assert await sweep.fetch_batch(None) is None  # every item is closed: nothing to scan
    assert await rig.state_of(first) == "executed"
    assert await rig.state_of(second.item_id) == "expired"
    assert (await rig.h.current(second_stored.key)).state == "expired"


def test_batch_limit_must_be_positive() -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.sweep(batch_limit=0)
