"""PRP-41 item 2: layered (store first, file fallback) producer registry."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_api.ingest.auth import (
    ProducerRegistration,
    RegisteredCredentialAuthenticator,
    StaticProducerRegistry,
    hash_secret,
)
from neurosphere_api.ingest.producer_store import (
    LayeredProducerRegistry,
    ProducerStoreSettings,
    StoreProducerRegistry,
)
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.producers import ProducerAdmin
from neurosphere_core.errors import UnauthorizedError

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
SOURCES: Any = {"gw-1": "gateway"}


def file_registration(producer_id: str, secret: str) -> ProducerRegistration:
    return ProducerRegistration(
        producer_id=producer_id,
        secret_sha256=hash_secret(secret),
        customer_id=CUSTOMER,
        cloud="commercial",
        sources={"file-src": "application"},
    )


async def setup() -> tuple[ProducerAdmin, InMemoryAdminConfigRepository, StoreProducerRegistry]:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    store = StoreProducerRegistry()
    return ProducerAdmin(repo, cloud="commercial"), repo, store


async def loader(repo: InMemoryAdminConfigRepository) -> Any:
    return await repo.list_by_kind(CUSTOMER, "producer", include_retired=True)


async def test_store_record_authenticates_after_refresh() -> None:
    admin, repo, store = await setup()
    result = await admin.create(
        CUSTOMER, "p1", cloud="commercial", sources=SOURCES, updated_by=ACTOR
    )
    assert result.issued is not None
    layered = LayeredProducerRegistry(store, StaticProducerRegistry([]))
    auth = RegisteredCredentialAuthenticator(layered)
    with pytest.raises(UnauthorizedError):  # not yet visible: fail closed
        auth.authenticate(f"Bearer p1.{result.issued.secret}")
    assert await store.refresh(lambda: loader(repo))
    assert auth.authenticate(f"Bearer p1.{result.issued.secret}").producer_id == "p1"


async def test_local_apply_is_immediate_and_disable_hides_file_entry() -> None:
    admin, _repo, store = await setup()
    file_reg = file_registration("p1", "file-secret-value")
    layered = LayeredProducerRegistry(store, StaticProducerRegistry([file_reg]))
    auth = RegisteredCredentialAuthenticator(layered)
    assert auth.authenticate("Bearer p1.file-secret-value").producer_id == "p1"
    created = await admin.create(
        CUSTOMER, "p1", cloud="commercial", sources=SOURCES, updated_by=ACTOR
    )
    assert created.issued is not None
    store.apply(created.document)
    # Store wins: the file secret no longer works, the issued one does.
    with pytest.raises(UnauthorizedError):
        auth.authenticate("Bearer p1.file-secret-value")
    assert auth.authenticate(f"Bearer p1.{created.issued.secret}").producer_id == "p1"
    off = await admin.set_status(
        CUSTOMER, "p1", "disabled", if_match=created.document.etag.root, updated_by=ACTOR
    )
    store.apply(off.document)
    for presented in ("file-secret-value", created.issued.secret):
        with pytest.raises(UnauthorizedError) as exc:
            auth.authenticate(f"Bearer p1.{presented}")
        assert str(exc.value) == "Producer credential rejected."


async def test_empty_store_behaves_as_static_registry() -> None:
    _, _, store = await setup()
    static = StaticProducerRegistry([file_registration("p9", "s9-secret")])
    layered = LayeredProducerRegistry(store, static)
    assert layered.get("p9") == static.get("p9")
    assert layered.get("unknown") is None


async def test_unknown_producer_keeps_the_same_rejection() -> None:
    _, _, store = await setup()
    auth = RegisteredCredentialAuthenticator(
        LayeredProducerRegistry(store, StaticProducerRegistry([]))
    )
    with pytest.raises(UnauthorizedError) as exc:
        auth.authenticate("Bearer ghost.whatever")
    assert str(exc.value) == "Producer credential rejected."


def test_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ProducerStoreSettings().store is False
    assert ProducerStoreSettings().refresh_seconds == 30.0
    monkeypatch.setenv("NS_INGEST_PRODUCER_STORE", "true")
    monkeypatch.setenv("NS_INGEST_PRODUCER_REFRESH_SECONDS", "5")
    conf = ProducerStoreSettings()
    assert conf.store is True and conf.refresh_seconds == 5.0
