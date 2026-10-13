"""Revocation stores: latest revocation wins, ETag-guarded writes, pseudonymous document ids."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.auth.revocation import (
    CosmosRevocationStore,
    InMemoryRevocationStore,
    RevocationEntry,
    RevocationStore,
    revocation_document_id,
)
from neurosphere_core.auth.revocation.cosmos_store import MAX_PUT_ATTEMPTS
from neurosphere_core.errors import DependencyTransientError
from pydantic import ValidationError

from .revocation_helpers import OBJECT_ID, FakeClock, entry_for, principal_id_for

TARGET = principal_id_for(OBJECT_ID)
NOW = FakeClock().datetime()


class _Container:
    """Cosmos-like fake: create-only ids, ETag preconditions on replace, system properties."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.version = 0
        self.calls: list[str] = []
        self.race: list[dict[str, Any]] = []  # bodies a "concurrent writer" lands before us
        self.put_error: BaseException | None = None

    def _land_race(self) -> None:
        if self.race:
            body = self.race.pop(0)
            self._store(body)

    def _store(self, body: dict[str, Any]) -> None:
        self.version += 1
        self.items[(body["id"], body["principal_id"])] = {
            **body,
            "_etag": f'"{self.version}"',
            "_rid": "r",
            "_ts": 1,
        }

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self.calls.append("read")
        try:
            return dict(self.items[(item, partition_key)])
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="missing") from None

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("create")
        if self.put_error is not None:
            raise self.put_error
        self._land_race()
        if (body["id"], body["principal_id"]) in self.items:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        self._store(body)
        return body

    async def replace_item(
        self, item: str, body: dict[str, Any], *, etag: str, match_condition: MatchConditions
    ) -> dict[str, Any]:
        self.calls.append("replace")
        assert match_condition is MatchConditions.IfNotModified
        self._land_race()
        current = self.items[(item, body["principal_id"])]
        if current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="etag")
        self._store(body)
        return body


def _cosmos(container: _Container) -> CosmosRevocationStore:
    return CosmosRevocationStore(cast(ContainerProxy, container), retention_seconds=120_000)


def _stores() -> list[tuple[str, RevocationStore, _Container | None]]:
    container = _Container()
    return [
        ("memory", InMemoryRevocationStore(), None),
        ("cosmos", _cosmos(container), container),
    ]


@pytest.mark.parametrize("index", [0, 1], ids=["memory", "cosmos"])
async def test_latest_revocation_wins(index: int) -> None:
    _, store, _ = _stores()[index]
    assert isinstance(store, RevocationStore)
    first = entry_for(TARGET, NOW)
    later = entry_for(TARGET, NOW + timedelta(minutes=5), reason="repeat")
    assert await store.put(first) == first
    assert await store.put(later) == later
    assert await store.put(first) == later  # an older revocation never rolls back a later one
    assert await store.get(TARGET) == later


async def test_cosmos_document_shape_is_pseudonymous_with_item_ttl() -> None:
    container = _Container()
    await _cosmos(container).put(entry_for(TARGET, NOW))
    [(key, doc)] = container.items.items()
    assert key == (revocation_document_id(TARGET), TARGET)
    assert doc["id"] == "revocation." + TARGET.rsplit(":", 1)[-1]
    assert doc["ttl"] == 120_000
    assert doc["doc_type"] == "revocation"
    assert OBJECT_ID not in repr(doc)


async def test_cosmos_put_retries_after_a_concurrent_writer() -> None:
    container = _Container()
    store = _cosmos(container)
    concurrent = entry_for(TARGET, NOW + timedelta(minutes=1))
    container.race.append(
        {
            **concurrent.model_dump(mode="json"),
            "id": revocation_document_id(TARGET),
            "doc_type": "revocation",
            "ttl": 120_000,
        }
    )
    mine = entry_for(TARGET, NOW + timedelta(minutes=2))
    assert await store.put(mine) == mine
    assert container.calls == ["read", "create", "read", "replace"]
    assert await store.get(TARGET) == mine


async def test_cosmos_put_keeps_later_concurrent_revocation() -> None:
    container = _Container()
    store = _cosmos(container)
    later = entry_for(TARGET, NOW + timedelta(minutes=9))
    container.race.append(
        {
            **later.model_dump(mode="json"),
            "id": revocation_document_id(TARGET),
            "doc_type": "revocation",
            "ttl": 120_000,
        }
    )
    assert await store.put(entry_for(TARGET, NOW)) == later


async def test_cosmos_put_gives_up_after_bounded_contention() -> None:
    container = _Container()
    store = _cosmos(container)
    await store.put(entry_for(TARGET, NOW))
    for i in range(MAX_PUT_ATTEMPTS):
        container.race.append(
            {
                **entry_for(TARGET, NOW + timedelta(seconds=i + 1)).model_dump(mode="json"),
                "id": revocation_document_id(TARGET),
                "doc_type": "revocation",
                "ttl": 120_000,
            }
        )
    with pytest.raises(DependencyTransientError) as info:
        await store.put(entry_for(TARGET, NOW + timedelta(hours=1)))
    assert info.value.reason == "revocation_store_conflict"


async def test_cosmos_write_failure_is_dependency_transient() -> None:
    container = _Container()
    container.put_error = RuntimeError("socket reset")
    with pytest.raises(DependencyTransientError) as info:
        await _cosmos(container).put(entry_for(TARGET, NOW))
    assert info.value.status == 503


def test_from_client_uses_injected_client() -> None:
    container = _Container()
    requested: list[tuple[str, str]] = []

    class _Db:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_container_client(self, name: str) -> _Container:
            requested.append((self.name, name))
            return container

    class _Client:
        def get_database_client(self, name: str) -> _Db:
            return _Db(name)

    CosmosRevocationStore.from_client(cast(CosmosClient, _Client()), database="neurosphere")
    assert requested == [("neurosphere", "revocations")]


@pytest.mark.parametrize(
    "fields",
    [
        {"principal_id": "alice@contoso.example"},
        {"principal_id": "commercial:contoso:entra:person:6c1d2e3f"},
        {"reason": "Free text with a Name"},
        {"revoked_at": NOW.replace(tzinfo=None)},
        {"unexpected": 1},
    ],
)
def test_entry_rejects_raw_ids_free_text_naive_times_and_extras(fields: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "principal_id": TARGET,
        "revoked_at": NOW,
        "reason": "compromised",
        "revoked_by": TARGET,
    }
    with pytest.raises(ValidationError):
        RevocationEntry.model_validate({**base, **fields})


def test_document_id_rejects_non_canonical_principal() -> None:
    with pytest.raises(ValueError):
        revocation_document_id("alice@contoso.example")
