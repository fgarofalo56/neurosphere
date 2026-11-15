"""PRP-39 item 1: block-until-lifted revocation, lift, no TTL on blocking entries."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.auth.revocation import (
    LIFT_ACTION,
    REVOKE_ACTION,
    CachedRevocationChecker,
    CosmosRevocationStore,
    InMemoryRevocationStore,
    RevocationEntry,
    RevocationHookRegistry,
    RevocationStore,
    merge_entries,
    revocation_document_id,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, NotFoundError
from pydantic import ValidationError

from .revocation_helpers import (
    ADMIN_OID,
    OBJECT_ID,
    FakeClock,
    FakePushRegistry,
    admin_scope,
    analyst_scope,
    entry_for,
    principal_id_for,
    service_for,
)

TARGET = principal_id_for(OBJECT_ID)
ADMIN = principal_id_for(ADMIN_OID)


def _block(at_offset: float, clock: FakeClock) -> RevocationEntry:
    return RevocationEntry(
        principal_id=TARGET,
        revoked_at=clock.datetime() + timedelta(seconds=at_offset),
        reason="compromised",
        revoked_by=ADMIN,
        mode="until_lifted",
    )


class _Container:
    """Minimal Cosmos fake: ETags, create-only ids, per-item ttl visible in ``items``."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.version = 0
        self.race: list[dict[str, Any]] = []

    def _store(self, body: dict[str, Any]) -> None:
        self.version += 1
        self.items[(body["id"], body["principal_id"])] = {**body, "_etag": f'"{self.version}"'}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        try:
            return dict(self.items[(item, partition_key)])
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="missing") from None

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        if (body["id"], body["principal_id"]) in self.items:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        self._store(body)
        return body

    async def replace_item(
        self, item: str, body: dict[str, Any], *, etag: str, match_condition: MatchConditions
    ) -> dict[str, Any]:
        assert match_condition is MatchConditions.IfNotModified
        if self.race:
            self._store(self.race.pop(0))
        if self.items[(item, body["principal_id"])]["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self._store(body)
        return body


def _cosmos(container: _Container) -> CosmosRevocationStore:
    return CosmosRevocationStore(cast(ContainerProxy, container), retention_seconds=120_000)


# ------------------------------------------------------------------ model


def test_stored_entries_without_mode_read_as_issued_before() -> None:
    raw = {
        "principal_id": TARGET,
        "revoked_at": "2027-01-15T08:00:00Z",
        "reason": "test",
        "revoked_by": ADMIN,
    }
    entry = RevocationEntry.model_validate(raw)
    assert entry.mode == "issued_before"
    assert entry.blocking is False


def test_lift_fields_are_set_together_and_never_on_a_block() -> None:
    clock = FakeClock()
    with pytest.raises(ValidationError):
        RevocationEntry(
            principal_id=TARGET,
            revoked_at=clock.datetime(),
            reason="x",
            revoked_by=ADMIN,
            lifted_at=clock.datetime(),
        )
    with pytest.raises(ValidationError):
        RevocationEntry(
            principal_id=TARGET,
            revoked_at=clock.datetime(),
            reason="x",
            revoked_by=ADMIN,
            mode="until_lifted",
            lifted_at=clock.datetime(),
            lifted_by=ADMIN,
        )


def test_merge_never_weakens_an_active_block() -> None:
    clock = FakeClock()
    block = _block(0, clock)
    later_ttl = entry_for(TARGET, clock.datetime() + timedelta(minutes=5))
    assert merge_entries(block, later_ttl) is block
    earlier_ttl = entry_for(TARGET, clock.datetime() + timedelta(minutes=9))
    merged = merge_entries(earlier_ttl, block)
    assert merged.blocking and merged.revoked_at == earlier_ttl.revoked_at
    newer_block = _block(60, clock)
    assert merge_entries(block, newer_block) is newer_block
    assert merge_entries(newer_block, block) is newer_block


# ------------------------------------------------------------------ stores


@pytest.mark.parametrize("kind", ["memory", "cosmos"])
async def test_store_lift_turns_block_into_issued_before(kind: str) -> None:
    clock = FakeClock()
    store: RevocationStore = (
        InMemoryRevocationStore(clock=clock) if kind == "memory" else _cosmos(_Container())
    )
    block = _block(0, clock)
    assert await store.put(block) == block
    assert await store.put(entry_for(TARGET, clock.datetime() + timedelta(seconds=5))) == block
    lifted = await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    assert lifted.mode == "issued_before"
    assert lifted.revoked_at == block.revoked_at
    assert lifted.lifted_by == ADMIN
    assert await store.get(TARGET) == lifted
    with pytest.raises(NotFoundError) as info:
        await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    assert info.value.reason == "no_active_block"


@pytest.mark.parametrize("kind", ["memory", "cosmos"])
async def test_lift_without_any_entry_is_not_found(kind: str) -> None:
    clock = FakeClock()
    store: RevocationStore = (
        InMemoryRevocationStore(clock=clock) if kind == "memory" else _cosmos(_Container())
    )
    with pytest.raises(NotFoundError):
        await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())


async def test_cosmos_block_has_no_item_ttl_and_lift_restores_retention() -> None:
    container = _Container()
    store = _cosmos(container)
    clock = FakeClock()
    await store.put(entry_for(TARGET, clock.datetime()))
    key = (revocation_document_id(TARGET), TARGET)
    assert container.items[key]["ttl"] == 120_000
    assert "mode" not in container.items[key]  # PRP-06 shape: old code still reads it
    await store.put(_block(1, clock))
    assert "ttl" not in container.items[key]
    assert container.items[key]["mode"] == "until_lifted"
    await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    assert container.items[key]["ttl"] == 120_000
    assert OBJECT_ID not in repr(container.items)


async def test_cosmos_lift_retries_when_the_entry_moves() -> None:
    container = _Container()
    store = _cosmos(container)
    clock = FakeClock()
    await store.put(_block(0, clock))
    newer = _block(30, clock).model_dump(mode="json", exclude_none=True)
    container.race.append({**newer, "id": revocation_document_id(TARGET), "doc_type": "x"})
    lifted = await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    assert lifted.revoked_at == clock.datetime() + timedelta(seconds=30)


async def test_memory_block_outlives_retention() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock, retention_seconds=100)
    await store.put(_block(0, clock))
    clock.advance(10_000)
    entry = await store.get(TARGET)
    assert entry is not None and entry.blocking
    await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    clock.advance(101)
    assert await store.get(TARGET) is None


async def test_lift_store_outage_is_dependency_transient() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    store.fail_with(DependencyTransientError("down", reason="revocation_store_unavailable"))
    with pytest.raises(DependencyTransientError):
        await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())


# ------------------------------------------------------------------ checker


async def test_until_lifted_denies_tokens_issued_after_revocation_until_lift_plus_ttl() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=60, clock_skew_seconds=60, clock=clock)
    await store.put(_block(0, clock))
    clock.advance(3600)
    fresh_token = clock.datetime()  # issued an hour after the block
    assert await checker.is_revoked(TARGET, fresh_token) is True

    await store.lift(TARGET, lifted_by=ADMIN, lifted_at=clock.datetime())
    clock.advance(59)  # another replica's cached "blocked" answer still stands
    assert await checker.is_revoked(TARGET, fresh_token) is True
    clock.advance(1)  # TTL elapsed: the lift is seen
    assert await checker.is_revoked(TARGET, fresh_token) is False
    # A token from before the block stays refused after the lift.
    assert await checker.is_revoked(TARGET, fresh_token - timedelta(hours=1)) is True


async def test_issued_before_behaviour_is_unchanged() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=60, clock_skew_seconds=0, clock=clock)
    await store.put(entry_for(TARGET, clock.datetime()))
    assert await checker.is_revoked(TARGET, clock.datetime()) is True
    assert await checker.is_revoked(TARGET, clock.datetime() + timedelta(seconds=1)) is False


# ------------------------------------------------------------------ service


async def test_service_revoke_until_lifted_then_lift_audited_and_fanned_out() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=60, clock=clock)
    hooks = RevocationHookRegistry()
    push = FakePushRegistry(sessions=2)
    hooks.register_push_registry("websocket", push)
    service, _, auditor = service_for(store, clock, hooks=hooks, checker=checker)
    actor = await admin_scope(clock)

    outcome = await service.revoke(actor, TARGET, reason="compromised", mode="until_lifted")
    assert outcome.entry.blocking
    assert outcome.fanout.sessions_closed == 2
    assert push.closed_for == [TARGET]
    clock.advance(600)
    assert await checker.is_revoked(TARGET, clock.datetime()) is True

    lifted = await service.lift(actor, TARGET, reason="investigation_closed")
    assert lifted.entry.mode == "issued_before"
    assert lifted.fanout.push_registries_called == 0
    assert push.closed_for == [TARGET]  # a lift closes nothing
    # The lifting replica invalidated its own cache: a new token is accepted at once.
    assert await checker.is_revoked(TARGET, clock.datetime()) is False

    assert [(e.action, e.phase) for e in auditor.events] == [
        (REVOKE_ACTION, "intent"),
        (REVOKE_ACTION, "outcome"),
        (LIFT_ACTION, "intent"),
        (LIFT_ACTION, "outcome"),
    ]
    assert auditor.events[0].mode == "until_lifted"
    assert auditor.events[3].mode == "issued_before"

    status = await service.status(actor, TARGET)
    assert status == lifted.entry


async def test_service_lift_denied_for_analyst_and_audited() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, auditor = service_for(store, clock)
    await store.put(_block(0, clock))
    with pytest.raises(ForbiddenError):
        await service.lift(await analyst_scope(clock), TARGET, reason="nope")
    assert [(e.action, e.phase) for e in auditor.events] == [(LIFT_ACTION, "denied")]
    entry = await store.get(TARGET)
    assert entry is not None and entry.blocking


async def test_service_lift_without_block_is_not_found_and_failure_audited() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, auditor = service_for(store, clock)
    with pytest.raises(NotFoundError):
        await service.lift(await admin_scope(clock), TARGET, reason="nothing_to_lift")
    assert auditor.phases == ["intent", "failed"]
    assert auditor.events[-1].error_code == "not_found"


async def test_service_status_outage_is_never_not_revoked() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, _ = service_for(store, clock)
    store.fail_with(RuntimeError("socket reset"))
    with pytest.raises(DependencyTransientError):
        await service.status(await admin_scope(clock), TARGET)
