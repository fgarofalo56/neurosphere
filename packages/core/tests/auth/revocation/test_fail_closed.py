"""A revocation store outage fails closed: ``dependency_transient`` (503), never "not revoked"."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    CosmosRevocationStore,
    InMemoryRevocationStore,
    RevocationEntry,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError

from .revocation_helpers import (
    OBJECT_ID,
    T0,
    FakeClock,
    admin_scope,
    entry_for,
    make_claims,
    make_deriver,
    policy_repo,
    principal_id_for,
    service_for,
)

TARGET = principal_id_for(OBJECT_ID)

OUTAGES: list[Exception] = [
    RuntimeError("socket reset"),
    ConnectionError("refused"),
    TimeoutError(),
    ServiceRequestError("dns failure"),
    CosmosHttpResponseError(status_code=503, message="service unavailable"),
    CosmosHttpResponseError(status_code=403, message="forbidden by store"),
    CosmosHttpResponseError(status_code=429, message="throttled"),
    DependencyTransientError("down", reason="revocation_store_unavailable"),
]


class _FakeContainer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        try:
            return dict(self.items[(item, partition_key)])
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="missing") from None


def _cosmos(container: _FakeContainer) -> CosmosRevocationStore:
    return CosmosRevocationStore(cast(ContainerProxy, container))


# ------------------------------------------------------------------ checker


@pytest.mark.parametrize("error", OUTAGES, ids=lambda e: type(e).__name__)
async def test_checker_outage_raises_dependency_transient(error: Exception) -> None:
    store = InMemoryRevocationStore()
    store.fail_with(error)
    checker = CachedRevocationChecker(store, clock=FakeClock())
    with pytest.raises(DependencyTransientError) as info:
        await checker.is_revoked(TARGET, FakeClock().datetime())
    assert info.value.status == 503


@pytest.mark.parametrize("error", OUTAGES, ids=lambda e: type(e).__name__)
async def test_derivation_with_store_outage_is_503_not_allow(error: Exception) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    store.fail_with(error)
    deriver = make_deriver(
        policy_repo(), clock=clock, revocation_checker=CachedRevocationChecker(store, clock=clock)
    )
    with pytest.raises(DependencyTransientError) as info:
        await deriver.from_verified_claims(make_claims())
    assert info.value.status == 503
    assert info.value.code == "dependency_transient"


async def test_expired_cache_is_not_served_during_outage_and_expiry_is_not_extended() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=30, clock=clock)
    issued = clock.datetime() - timedelta(minutes=1)
    assert await checker.is_revoked(TARGET, issued) is False

    store.fail_with(RuntimeError("down"))
    clock.now = T0 + 29  # stale-but-unexpired may serve (same rule as the policy cache, C14)
    assert await checker.is_revoked(TARGET, issued) is False
    clock.now = T0 + 30  # expired: the outage surfaces as 503
    with pytest.raises(DependencyTransientError):
        await checker.is_revoked(TARGET, issued)
    clock.now = T0 + 31  # the failed reload did not refresh or extend the entry
    with pytest.raises(DependencyTransientError):
        await checker.is_revoked(TARGET, issued)

    store.fail_with(None)
    await store.put(entry_for(TARGET, clock.datetime()))
    assert await checker.is_revoked(TARGET, issued) is True


async def test_store_returning_another_principals_entry_fails_closed() -> None:
    other = principal_id_for("00000000-0000-4000-8000-0000000000aa")

    class WrongStore:
        async def get(self, principal_id: str) -> RevocationEntry | None:
            return entry_for(other, FakeClock().datetime())

        async def put(self, entry: RevocationEntry) -> RevocationEntry:
            return entry

    with pytest.raises(DependencyTransientError) as info:
        await CachedRevocationChecker(WrongStore()).is_revoked(TARGET, FakeClock().datetime())
    assert info.value.status == 502


# ------------------------------------------------------------------ Cosmos store


@pytest.mark.parametrize("error", OUTAGES[:-1], ids=lambda e: type(e).__name__)
async def test_cosmos_read_failure_is_dependency_transient(error: BaseException) -> None:
    store = _cosmos(_FakeContainer(error))
    with pytest.raises(DependencyTransientError) as info:
        await store.get(TARGET)
    assert info.value.status == 503
    assert info.value.reason == "revocation_store_unavailable"
    assert str(info.value) == "revocation store unavailable"  # no SDK text echoed


async def test_cosmos_not_found_is_the_only_not_revoked_answer() -> None:
    assert await _cosmos(_FakeContainer()).get(TARGET) is None


@pytest.mark.parametrize(
    "document",
    [
        {"principal_id": TARGET, "revoked_at": "not-a-time"},
        {"principal_id": TARGET, "revoked_at": "2027-01-15T08:00:00Z", "reason": "x"},
        {
            "principal_id": principal_id_for("00000000-0000-4000-8000-0000000000bb"),
            "revoked_at": "2027-01-15T08:00:00Z",
            "reason": "x",
            "revoked_by": TARGET,
        },
    ],
)
async def test_cosmos_invalid_document_is_502(document: dict[str, Any]) -> None:
    container = _FakeContainer()
    doc_id = "revocation." + TARGET.rsplit(":", 1)[-1]
    container.items[(doc_id, TARGET)] = document
    with pytest.raises(DependencyTransientError) as info:
        await _cosmos(container).get(TARGET)
    assert info.value.status == 502


# ------------------------------------------------------------------ admin revoke


async def test_revoke_with_store_outage_raises_and_does_not_fan_out() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, hooks, auditor = service_for(store, clock)
    calls: list[str] = []
    hooks.register_cache_invalidator("cache", calls.append)
    actor = await admin_scope(clock)
    store.fail_with(RuntimeError("down"))

    with pytest.raises(DependencyTransientError) as info:
        await service.revoke(actor, TARGET, reason="compromised")
    assert info.value.status == 503
    assert calls == []
    assert auditor.phases == ["intent", "failed"]
    assert auditor.events[-1].error_code == "dependency_transient"


async def test_revoke_store_outage_with_failing_failure_audit_still_raises_store_error() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    service, _, auditor = service_for(store, clock)
    actor = await admin_scope(clock)
    auditor.fail_on.add("failed")
    store.fail_with(DependencyTransientError("down", reason="revocation_store_unavailable"))
    with pytest.raises(DependencyTransientError) as info:
        await service.revoke(actor, TARGET, reason="compromised")
    assert info.value.reason == "revocation_store_unavailable"


async def test_revoked_principal_stays_denied_while_store_is_healthy_then_503_on_outage() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=10, clock=clock)
    deriver = make_deriver(policy_repo(), clock=clock, revocation_checker=checker)
    await store.put(entry_for(TARGET, clock.datetime()))
    with pytest.raises(ForbiddenError):
        await deriver.from_verified_claims(make_claims())
    store.fail_with(RuntimeError("down"))
    clock.now = T0 + 10
    with pytest.raises(DependencyTransientError):  # never flips to allowed
        await deriver.from_verified_claims(make_claims())
