"""Ownership register, guard and removal path (PRP-08 item 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from neurosphere_core.deploy.register import (
    Action,
    ConsentRecord,
    InMemoryRegisterStore,
    Ownership,
    RegisterExport,
    ResourceRow,
    assert_removable,
    plan_removal,
    record_consent,
    remove,
)
from neurosphere_core.errors import ForbiddenError
from pydantic import ValidationError

SUB = "/subscriptions/00000000-0000-0000-0000-000000000000"
RG = f"{SUB}/resourceGroups/rg-ns"
DEP = "dep-1"
NOW = datetime(2026, 10, 16, tzinfo=UTC)


def rid(name: str) -> str:
    return f"{RG}/providers/Microsoft.Test/things/{name}"


def row(name: str, ownership: str = "created", **over: Any) -> ResourceRow:
    base: dict[str, Any] = {
        "deployment_id": DEP,
        "resource_id": rid(name),
        "service": "cosmos",
        "ownership": ownership,
        "owner": "principal:abc123",
        "creating_plan_id": "plan-1",
        "recorded_at": NOW,
    }
    if ownership == "created":
        base["created_by"] = "neurosphere"
    else:
        base["consent_reference"] = "consent-1"
    base.update(over)
    return ResourceRow(**base)


class RecordingDeleter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def delete(self, resource_id: str) -> None:
        self.calls.append(resource_id)


def test_row_records_owner_consent_dependents_plan() -> None:
    r = row("a", "reused", dependents=(rid("x"),))
    assert r.owner == "principal:abc123"
    assert r.consent_reference == "consent-1"
    assert r.dependents == (rid("x"),)
    assert r.creating_plan_id == "plan-1"


@pytest.mark.parametrize(
    "over",
    [
        {"ownership": "created", "created_by": "someone-else"},
        {"ownership": "created", "created_by": None},
        {"ownership": "created", "consent_reference": "c"},
        {"ownership": "reused", "created_by": "neurosphere"},
        {"ownership": "reused", "consent_reference": None},
        {"ownership": "shared", "consent_reference": None},
        {"owner": "someone@example.com"},
        {"owner": "Jane Doe"},
        {"recorded_at": datetime(2026, 1, 1)},
        {"recorded_at": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))},
        {"resource_id": "not-an-arm-id"},
        {"dependents": ("nope",)},
        {"dependents": (rid("a"),)},
        {"surprise": 1},
    ],
)
def test_invalid_rows_fail_validation(over: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "deployment_id": DEP,
        "resource_id": rid("a"),
        "service": "cosmos",
        "ownership": "created",
        "created_by": "neurosphere",
        "owner": "principal:abc123",
        "creating_plan_id": "plan-1",
        "recorded_at": NOW,
    }
    base.update(over)
    with pytest.raises(ValidationError):
        ResourceRow(**base)


def test_export_rejects_mixed_deployments() -> None:
    with pytest.raises(ValidationError):
        RegisterExport(deployment_id="other", rows=(row("a"),))


@pytest.mark.parametrize("ownership", ["reused", "shared"])
def test_guard_raises_for_reused_and_shared(ownership: str) -> None:
    r = row("a", ownership)
    with pytest.raises(ForbiddenError):
        assert_removable(r, [r])


def test_guard_raises_for_foreign_dependents_and_unrecorded_rows() -> None:
    r = row("a", dependents=(rid("outsider"),))
    with pytest.raises(ForbiddenError):
        assert_removable(r, [r])
    with pytest.raises(ForbiddenError):
        assert_removable(row("b"), [])  # not in the register passed as context


def test_guard_allows_created_with_created_dependents() -> None:
    a, b = row("a", dependents=(rid("b"),)), row("b")
    assert_removable(a, [a, b])


def test_resource_group_with_reused_child_is_not_removable() -> None:
    group = row("g", resource_id=RG)
    child = row("kv", "reused")
    with pytest.raises(ForbiddenError):
        assert_removable(group, [group, child])


def test_plan_orders_dependents_first_and_lists_untouched() -> None:
    # app depends on db depends on kv; shared + reused are untouched.
    kv = row("kv", dependents=(rid("db"),))
    db = row("db", dependents=(rid("app"),))
    app = row("app")
    reused = row("old", "reused")
    shared = row("hub", "shared")
    plan = plan_removal(DEP, [kv, db, app, reused, shared])
    assert [e.resource_id for e in plan.removable] == [rid("app"), rid("db"), rid("kv")]
    untouched = {e.resource_id: e for e in plan.entries if e.action is Action.UNTOUCHED}
    assert set(untouched) == {rid("old"), rid("hub")}
    assert all(e.reason for e in untouched.values())


def test_plan_blocks_dependency_of_blocked_dependent() -> None:
    kv = row("kv", dependents=(rid("db"),))
    db = row("db", dependents=(rid("outsider"),))
    plan = plan_removal(DEP, [kv, db])
    assert plan.removable == ()


def test_plan_reports_unregistered_as_untouched() -> None:
    plan = plan_removal(DEP, [row("a")], unregistered_ids=[rid("ghost"), rid("A")])
    ghost = [e for e in plan.entries if e.resource_id == rid("ghost")]
    assert ghost[0].action is Action.UNTOUCHED
    assert len(plan.entries) == 2  # the case-variant of a registered row is not duplicated


async def test_remove_never_calls_deleter_for_reused_shared_or_tagged_resources() -> None:
    # The register is the only authority: a resource tagged neurosphere:created-by=neurosphere
    # in Azure but recorded as reused is untouched. Tags are not an input to remove() at all.
    tagged_but_reused = row("tagged", "reused")
    shared = row("hub", "shared")
    created = row("mine")
    deleter = RecordingDeleter()
    deleted = await remove(DEP, [tagged_but_reused, shared, created], deleter)
    assert deleted == [rid("mine")]
    assert deleter.calls == [rid("mine")]


async def test_remove_with_only_protected_rows_makes_zero_calls() -> None:
    deleter = RecordingDeleter()
    deleted = await remove(DEP, [row("a", "reused"), row("b", "shared")], deleter)
    assert deleted == []
    assert deleter.calls == []


async def test_remove_reruns_guard_before_each_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    import neurosphere_core.deploy.register.guard as guard

    seen: list[str] = []
    real = guard.assert_removable

    def spy(r: ResourceRow, register: Any) -> None:
        seen.append(r.resource_id)
        real(r, register)

    monkeypatch.setattr(guard, "assert_removable", spy)
    deleter = RecordingDeleter()
    await remove(DEP, [row("a")], deleter)
    # once during planning, once immediately before the delete
    assert seen.count(rid("a")) == 2


async def test_store_blocks_ownership_downgrade() -> None:
    store = InMemoryRegisterStore()
    await store.put_row(row("a", "reused"))
    with pytest.raises(ForbiddenError):
        await store.put_row(row("a", "created"))
    with pytest.raises(ForbiddenError):  # case-insensitive ARM id
        await store.put_row(row("a", "created", resource_id=rid("a").upper()))
    got = await store.get_row(DEP, rid("a"))
    assert got is not None
    assert got.ownership is Ownership.REUSED


async def test_store_allows_upgrade_and_reused_to_shared() -> None:
    store = InMemoryRegisterStore()
    await store.put_row(row("a"))
    await store.put_row(row("a", "shared"))
    await store.put_row(row("a", "reused"))
    rows = await store.list_rows(DEP)
    assert [r.ownership for r in rows] == [Ownership.REUSED]


async def test_consent_is_stored_and_audited() -> None:
    store = InMemoryRegisterStore()
    events: list[str] = []

    class Sink:
        async def consent_recorded(self, consent: ConsentRecord) -> None:
            events.append(consent.consent_id)

    consent = ConsentRecord(
        deployment_id=DEP,
        consent_id="consent-1",
        owner="principal:abc123",
        resource_ids=(rid("a"),),
        granted_at=NOW,
        plan_id="plan-1",
    )
    await record_consent(store, consent, Sink())
    await record_consent(store, consent)  # default no-op sink
    assert await store.list_consents(DEP) == [consent]
    assert events == ["consent-1"]


class FakeInventory:
    def __init__(self, live: list[str] | None = None, error: Exception | None = None) -> None:
        self.live = live or []
        self.error = error
        self.listed: list[str] = []

    async def list_resource_group(self, rg_id: str) -> list[str]:
        self.listed.append(rg_id)
        if self.error is not None:
            raise self.error
        return list(self.live)


def rg_row() -> ResourceRow:
    return row("rg", resource_id=RG, service="resource-group")


async def test_remove_refuses_resource_group_without_inventory() -> None:
    deleter = RecordingDeleter()
    with pytest.raises(ForbiddenError):
        await remove(DEP, [row("a"), rg_row()], deleter)
    assert deleter.calls == []


async def test_remove_refuses_foreign_live_resource_in_group_with_zero_deletes() -> None:
    foreign = f"{RG}/providers/Microsoft.Storage/storageAccounts/foreign"
    inventory = FakeInventory([rid("a"), foreign.upper()])
    deleter = RecordingDeleter()
    with pytest.raises(ForbiddenError, match="not created by NeuroSphere"):
        await remove(DEP, [row("a"), rg_row()], deleter, inventory)
    assert deleter.calls == []


async def test_remove_refuses_when_listing_fails_with_zero_deletes() -> None:
    deleter = RecordingDeleter()
    with pytest.raises(ForbiddenError, match="cannot verify"):
        await remove(DEP, [row("a"), rg_row()], deleter, FakeInventory(error=RuntimeError("503")))
    assert deleter.calls == []


async def test_remove_deletes_group_after_children_when_inventory_matches() -> None:
    inventory = FakeInventory([rid("A"), rid("b")])  # case-insensitive match
    deleter = RecordingDeleter()
    deleted = await remove(DEP, [rg_row(), row("a"), row("b")], deleter, inventory)
    assert deleted[-1] == RG
    assert set(deleted[:-1]) == {rid("a"), rid("b")}
    assert deleter.calls == deleted
    assert len(inventory.listed) == 2  # verified up front and re-listed before the group delete


async def test_remove_rechecks_group_immediately_before_delete() -> None:
    class Drifting(FakeInventory):
        async def list_resource_group(self, rg_id: str) -> list[str]:
            await super().list_resource_group(rg_id)
            if len(self.listed) > 1:
                return [rid("a"), f"{RG}/providers/Microsoft.Test/things/late"]
            return [rid("a")]

    deleter = RecordingDeleter()
    with pytest.raises(ForbiddenError):
        await remove(DEP, [rg_row(), row("a")], deleter, Drifting())
    assert RG not in deleter.calls


def test_plan_reports_foreign_live_resource_as_reason_group_untouched() -> None:
    foreign = f"{RG}/providers/Microsoft.Storage/storageAccounts/foreign"
    plan = plan_removal(DEP, [rg_row(), row("a")], live_contents={RG: [rid("a"), foreign]})
    by_id = {e.resource_id: e for e in plan.entries}
    assert by_id[RG].action is Action.UNTOUCHED
    assert foreign in (by_id[RG].reason or "")
    assert by_id[rid("a")].action is Action.REMOVABLE


def test_plan_without_inventory_labels_group_unverified() -> None:
    plan = plan_removal(DEP, [rg_row(), row("a")])
    by_id = {e.resource_id: e for e in plan.entries}
    assert by_id[RG].action is Action.REMOVABLE
    assert by_id[RG].reason == "live contents not verified (dry-run)"
    assert [e.resource_id for e in plan.removable][-1] == RG


def test_consent_requires_resources_and_pseudonymous_owner() -> None:
    with pytest.raises(ValidationError):
        ConsentRecord(
            deployment_id=DEP,
            consent_id="c",
            owner="a@b.c",
            resource_ids=(rid("a"),),
            granted_at=NOW,
            plan_id="p",
        )
    with pytest.raises(ValidationError):
        ConsentRecord(
            deployment_id=DEP,
            consent_id="c",
            owner="principal:x1",
            resource_ids=(),
            granted_at=NOW,
            plan_id="p",
        )
