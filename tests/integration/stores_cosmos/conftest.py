"""Emulator fixtures for the Cosmos store conformance suites.

Run: ``pytest -m integration tests/integration/stores_cosmos`` against the compose Cosmos emulator
(``http://127.0.0.1:8081``). Every test gets its OWN database (unique name, deleted afterwards), so
nothing is shared and nothing is left behind. The key is a dummy built at runtime: the emulator
ignores it (G12), and no key-shaped literal is committed.

Emulator limits (G12): no auth, no RU accounting. Passing here proves the SQL shapes and the
hierarchical/hash partition keys work against the emulator, not RBAC, RU cost or consistency.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from azure.cosmos import CosmosClient as SyncCosmosClient
from azure.cosmos import DatabaseProxy as SyncDatabaseProxy
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

ENDPOINT = "http://127.0.0.1:8081"


def _dummy_key() -> str:
    return base64.b64encode(b"emulator-ignores-this").decode()


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("NS_COSMOS_KEY", _dummy_key())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    """A fresh async database, deleted afterwards."""
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = await client.create_database_if_not_exists(f"ns_stores_{uuid.uuid4().hex[:12]}")
        try:
            yield db
        finally:
            await client.delete_database(db.id)


@pytest.fixture
def sync_database() -> Iterator[SyncDatabaseProxy]:
    """A fresh sync database (the price snapshot protocol is synchronous), deleted afterwards."""
    client = SyncCosmosClient(ENDPOINT, _dummy_key(), enable_endpoint_discovery=False)
    db = client.create_database_if_not_exists(f"ns_stores_{uuid.uuid4().hex[:12]}")
    try:
        yield db
    finally:
        client.delete_database(db.id)
        client.close()
