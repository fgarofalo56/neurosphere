"""CosmosConversationStore against the compose emulator (PRP-19 item 2). Not run in CI.

Run: ``docker compose up -d --wait`` then ``pytest -m integration services/api/tests/copilot_api``.
Each test gets its own container (deleted afterwards). Emulator limits (G12): no auth, no RU
accounting; this proves the owner partitioning, per-document ``ttl`` fields and queries work on
a real Cosmos API surface, and says nothing about RBAC, RU cost or TTL eviction timing.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from neurosphere_api.copilot import (
    CosmosConversationStore,
    StoredConversation,
    StoredTurn,
    create_conversation_container,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

pytestmark = pytest.mark.integration

T0 = datetime.now(UTC).replace(microsecond=0)
OWNER = "commercial:contoso:entra:person:psn_owner0000000001"
OTHER = "commercial:contoso:entra:person:psn_other0000000002"


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_copilot_it")


@pytest_asyncio.fixture
async def container(database: DatabaseProxy) -> AsyncIterator[ContainerProxy]:
    name = f"conversations_{uuid4().hex[:8]}"
    created = await create_conversation_container(database, name)
    try:
        yield created
    finally:
        await database.delete_container(name)


def _turn(message_id: str, conversation_id: str, role: str, at: datetime) -> StoredTurn:
    return StoredTurn(
        message_id=message_id,
        conversation_id=conversation_id,
        role=role,  # type: ignore[arg-type]
        text="redacted text",
        status="answered" if role == "assistant" else None,
        reason_code=None,
        citations=(),
        context=None,
        created_at=at,
        retention_class="standard",
        expires_at=at + timedelta(days=30),
    )


async def test_roundtrip_isolation_and_delete_on_the_emulator(container: ContainerProxy) -> None:
    store = CosmosConversationStore(container)
    cid = str(uuid4())
    await store.create(
        StoredConversation(
            id=cid,
            owner=OWNER,
            created_at=T0,
            updated_at=T0,
            retention_class="standard",
            expires_at=T0 + timedelta(days=30),
        )
    )
    turns = [
        _turn(str(uuid4()), cid, "user", T0),
        _turn(str(uuid4()), cid, "assistant", T0 + timedelta(milliseconds=1)),
    ]
    appended = await store.append(OWNER, cid, turns, now=T0)
    assert appended

    assert [t.role for t in await store.load_turns(OWNER, cid, limit=None, now=T0)] == [
        "user",
        "assistant",
    ]
    assert await store.get(OTHER, cid, now=T0) is None
    assert await store.load_turns(OTHER, cid, limit=None, now=T0) == []
    listed, cursor = await store.list_conversations(OWNER, cursor=None, limit=5, now=T0)
    assert [c.id for c in listed] == [cid] and cursor is None

    raw = await container.read_item(item=turns[0].message_id, partition_key=OWNER)
    assert raw["ttl"] == 30 * 86400 and raw["owner"] == OWNER

    foreign_delete = await store.delete(OTHER, cid)
    assert not foreign_delete
    owner_delete = await store.delete(OWNER, cid)
    assert owner_delete
    assert await store.get(OWNER, cid, now=T0) is None
