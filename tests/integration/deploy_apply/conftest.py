"""Emulator fixtures for the deploy apply twin (PRP-55 item 6).

Run: ``pytest -m integration tests/integration/deploy_apply`` against the compose Cosmos emulator
(``http://127.0.0.1:8081``; 127.0.0.1, never localhost). Every test gets its own database with
the two registry containers it needs, deleted afterwards. The key is a dummy built at runtime:
the emulator ignores it, and no key-shaped literal is committed.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from azure.cosmos.aio import CosmosClient, DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.stores import container_spec

ENDPOINT = "http://127.0.0.1:8081"
CONTAINERS = ("deploy_plan_approvals", "deploy_register")


def _dummy_key() -> str:
    return base64.b64encode(b"emulator-ignores-this").decode()


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("NS_COSMOS_KEY", _dummy_key())


@pytest_asyncio.fixture
async def emulator() -> AsyncIterator[tuple[CosmosClient, DatabaseProxy]]:
    """A fresh database holding the approvals and register containers, deleted afterwards."""
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = await client.create_database_if_not_exists(f"ns_deploy_{uuid.uuid4().hex[:12]}")
        try:
            for name in CONTAINERS:
                await db.create_container_if_not_exists(
                    id=name, partition_key=container_spec(name).partition_key()
                )
            yield client, db
        finally:
            await client.delete_database(db.id)
