"""PRP-41 item 2: a failing store never raises into a request and keeps the last snapshot."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.ingest.auth import (
    RegisteredCredentialAuthenticator,
    StaticProducerRegistry,
)
from neurosphere_api.ingest.producer_store import (
    REASON_STORE_UNAVAILABLE,
    LayeredProducerRegistry,
    StoreProducerRegistry,
)
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.producers import ProducerAdmin
from neurosphere_core.errors import DependencyTransientError, UnauthorizedError

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
SOURCES: Any = {"gw-1": "gateway"}


async def test_failure_before_first_refresh_fails_closed_with_reason_code() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    repo.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    store = StoreProducerRegistry()

    async def load() -> Any:
        return await repo.list_by_kind(CUSTOMER, "producer", include_retired=True)

    assert await store.refresh(load) is False
    assert store.last_reason == REASON_STORE_UNAVAILABLE
    auth = RegisteredCredentialAuthenticator(
        LayeredProducerRegistry(store, StaticProducerRegistry([]))
    )
    with pytest.raises(UnauthorizedError):
        auth.authenticate("Bearer p1.anything")


async def test_failure_keeps_last_snapshot_and_recovers() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    admin = ProducerAdmin(repo, cloud="commercial")
    created = await admin.create(
        CUSTOMER, "p1", cloud="commercial", sources=SOURCES, updated_by=ACTOR
    )
    assert created.issued is not None
    store = StoreProducerRegistry()

    async def load() -> Any:
        return await repo.list_by_kind(CUSTOMER, "producer", include_retired=True)

    assert await store.refresh(load)
    assert store.last_reason is None
    repo.fail_with(RuntimeError("boom with secret-looking text"))
    assert await store.refresh(load) is False
    assert store.last_reason == REASON_STORE_UNAVAILABLE
    assert store.get("p1") is not None  # last snapshot kept
    repo.fail_with(None)
    assert await store.refresh(load)
    assert store.last_reason is None
