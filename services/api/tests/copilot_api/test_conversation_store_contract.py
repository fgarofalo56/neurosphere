"""One contract, two stores (PRP-19 item 2): in-memory and Cosmos (over a faithful fake container).

The Cosmos store is exercised against ``FakeContainer``, an in-process stand-in that honours what
the store relies on: partition-scoped reads, create-only ``create_item``, per-document ``ttl``
and the four fixed parameterized queries. The emulator run lives in
``test_conversation_store_emulator.py`` (marked ``integration``; not run in CI).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from neurosphere_api.copilot import (
    ConversationStore,
    CosmosConversationStore,
    InMemoryConversationStore,
    StoredConversation,
    StoredTurn,
)
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError

T0 = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
OWNER = "commercial:contoso:entra:person:psn_owner0000000001"
OTHER = "commercial:contoso:entra:person:psn_other0000000002"


class FakeContainer:
    """Just enough of ``ContainerProxy`` (async) for ``CosmosConversationStore``."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise RuntimeError("boom")  # an SDK/network failure of any kind

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self._check()
        try:
            return dict(self.docs[(partition_key, item)])
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="not found") from None

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._check()
        key = (body["owner"], body["id"])
        if key in self.docs:
            raise CosmosResourceExistsError(status_code=409, message="exists")
        self.docs[key] = dict(body)
        return dict(body)

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self._check()
        self.docs[(body["owner"], body["id"])] = dict(body)
        return dict(body)

    async def delete_item(self, item: str, partition_key: str) -> None:
        self._check()
        try:
            del self.docs[(partition_key, item)]
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="not found") from None

    def query_items(
        self, query: str, parameters: list[dict[str, Any]], partition_key: str
    ) -> AsyncIterator[dict[str, Any]]:
        self._check()
        params = {p["name"]: p["value"] for p in parameters}
        rows = [d for (owner, _), d in self.docs.items() if owner == partition_key]
        if "doc_type = 'conversation'" in query:
            rows = [
                d
                for d in rows
                if d["doc_type"] == "conversation" and d["sort_key"] < params["@after"]
            ]
            rows.sort(key=lambda d: d["sort_key"], reverse=True)
        elif "doc_type = 'turn'" in query:
            rows = [
                d
                for d in rows
                if d["doc_type"] == "turn" and d["conversation_id"] == params["@conversation"]
            ]
            rows.sort(key=lambda d: d["sort_key"])
        else:  # SELECT c.id ... WHERE c.conversation_id = @conversation
            rows = [
                {"id": d["id"]} for d in rows if d.get("conversation_id") == params["@conversation"]
            ]

        async def iterate() -> AsyncIterator[dict[str, Any]]:
            for row in rows:
                yield dict(row)

        return iterate()


@pytest.fixture(params=["memory", "cosmos-fake"])
def store(request: pytest.FixtureRequest) -> ConversationStore:
    if request.param == "memory":
        return InMemoryConversationStore()
    return CosmosConversationStore(FakeContainer())  # type: ignore[arg-type]


def conversation(
    cid: str, owner: str = OWNER, *, at: datetime = T0, days: int = 30
) -> StoredConversation:
    return StoredConversation(
        id=cid,
        owner=owner,
        created_at=at,
        updated_at=at,
        retention_class="standard",
        expires_at=at + timedelta(days=days),
    )


def turn(
    mid: str, cid: str, role: str, at: datetime, *, text: str = "t", days: int = 30
) -> StoredTurn:
    return StoredTurn(
        message_id=mid,
        conversation_id=cid,
        role=role,  # type: ignore[arg-type]
        text=text,
        status="answered" if role == "assistant" else None,
        reason_code=None,
        citations=(
            {
                "record_id": "x",
                "kind": "agent",
                "source": "catalog",
                "as_of": None,
                "freshness": "unknown",
            },
        )
        if role == "assistant"
        else (),
        context={"page": "catalog"} if role == "user" else None,
        created_at=at,
        retention_class="standard",
        expires_at=at + timedelta(days=days),
    )


async def test_create_get_append_and_order(store: ConversationStore) -> None:
    await store.create(conversation("c1"))
    assert (await store.get(OWNER, "c1", now=T0)) is not None
    turns = [
        turn("m2", "c1", "assistant", T0 + timedelta(seconds=2), text="answer"),
        turn("m1", "c1", "user", T0 + timedelta(seconds=1), text="question"),
    ]
    appended = await store.append(OWNER, "c1", turns, now=T0 + timedelta(seconds=3))
    assert appended
    loaded = await store.load_turns(OWNER, "c1", limit=None, now=T0)
    assert [t.message_id for t in loaded] == ["m1", "m2"]  # oldest first regardless of insert order
    assert loaded[1].citations[0]["record_id"] == "x" and loaded[0].context == {"page": "catalog"}
    assert [t.message_id for t in await store.load_turns(OWNER, "c1", limit=1, now=T0)] == ["m2"]


async def test_another_owner_sees_nothing_and_cannot_write_or_delete(
    store: ConversationStore,
) -> None:
    await store.create(conversation("c1"))
    await store.append(OWNER, "c1", [turn("m1", "c1", "user", T0)], now=T0)
    assert await store.get(OTHER, "c1", now=T0) is None
    assert await store.load_turns(OTHER, "c1", limit=None, now=T0) == []
    foreign_append = await store.append(OTHER, "c1", [turn("m9", "c1", "user", T0)], now=T0)
    assert not foreign_append
    foreign_delete = await store.delete(OTHER, "c1")
    assert not foreign_delete
    items, _ = await store.list_conversations(OTHER, cursor=None, limit=10, now=T0)
    assert items == []
    assert [t.message_id for t in await store.load_turns(OWNER, "c1", limit=None, now=T0)] == ["m1"]


async def test_expired_turns_and_conversations_are_invisible(store: ConversationStore) -> None:
    await store.create(conversation("c1", days=30))
    short = turn("m1", "c1", "user", T0, days=7)
    long = turn("m2", "c1", "assistant", T0 + timedelta(seconds=1), days=30)
    await store.append(OWNER, "c1", [short, long], now=T0)

    later = T0 + timedelta(days=8)
    assert [t.message_id for t in await store.load_turns(OWNER, "c1", limit=None, now=later)] == [
        "m2"
    ]
    assert await store.get(OWNER, "c1", now=T0 + timedelta(days=31)) is None
    expired_append = await store.append(
        OWNER, "c1", [turn("m3", "c1", "user", later)], now=T0 + timedelta(days=31)
    )
    assert not expired_append
    listed, _ = await store.list_conversations(
        OWNER, cursor=None, limit=10, now=T0 + timedelta(days=31)
    )
    assert listed == []


async def test_append_extends_the_conversation_to_its_newest_turn(store: ConversationStore) -> None:
    await store.create(conversation("c1", days=1))
    await store.append(OWNER, "c1", [turn("m1", "c1", "user", T0, days=30)], now=T0)
    found = await store.get(OWNER, "c1", now=T0 + timedelta(days=2))
    assert found is not None and found.expires_at == T0 + timedelta(days=30)


async def test_list_is_newest_first_paged_and_owner_only(store: ConversationStore) -> None:
    for n in range(5):
        await store.create(conversation(f"c{n}", at=T0 + timedelta(minutes=n)))
    await store.create(conversation("theirs", OTHER, at=T0 + timedelta(minutes=9)))

    first, cursor = await store.list_conversations(OWNER, cursor=None, limit=2, now=T0)
    assert [c.id for c in first] == ["c4", "c3"] and cursor is not None
    second, cursor2 = await store.list_conversations(OWNER, cursor=cursor, limit=2, now=T0)
    assert [c.id for c in second] == ["c2", "c1"] and cursor2 is not None
    last, cursor3 = await store.list_conversations(OWNER, cursor=cursor2, limit=2, now=T0)
    assert [c.id for c in last] == ["c0"] and cursor3 is None


async def test_a_malformed_cursor_is_invalid_schema(store: ConversationStore) -> None:
    with pytest.raises(InvalidSchemaError):
        await store.list_conversations(OWNER, cursor="@@@not-base64", limit=5, now=T0)


async def test_delete_removes_the_conversation_and_every_turn(store: ConversationStore) -> None:
    await store.create(conversation("c1"))
    await store.append(
        OWNER, "c1", [turn("m1", "c1", "user", T0), turn("m2", "c1", "assistant", T0)], now=T0
    )
    deleted = await store.delete(OWNER, "c1")
    assert deleted
    assert await store.get(OWNER, "c1", now=T0) is None
    assert await store.load_turns(OWNER, "c1", limit=None, now=T0) == []
    deleted_again = await store.delete(OWNER, "c1")
    assert not deleted_again
    if isinstance(store, InMemoryConversationStore):
        assert store.raw_documents() == []


# -- Cosmos-specific: partitioning, TTL, failure mapping ----------------------------------------


async def test_cosmos_documents_are_owner_partitioned_with_per_document_ttl() -> None:
    container = FakeContainer()
    store = CosmosConversationStore(container)  # type: ignore[arg-type]
    await store.create(conversation("c1", days=30))
    await store.append(
        OWNER,
        "c1",
        [turn("m1", "c1", "user", T0, days=7), turn("m2", "c1", "assistant", T0, days=30)],
        now=T0,
    )
    assert {owner for owner, _ in container.docs} == {OWNER}
    ttl = {doc_id: doc["ttl"] for (_, doc_id), doc in container.docs.items()}
    assert ttl["m1"] == 7 * 86400 and ttl["m2"] == 30 * 86400 and ttl["c1"] == 30 * 86400
    assert all(doc["owner"] == OWNER for doc in container.docs.values())


async def test_cosmos_failures_map_to_the_taxonomy_without_leaking_details() -> None:
    container = FakeContainer()
    store = CosmosConversationStore(container)  # type: ignore[arg-type]
    container.fail = True
    with pytest.raises(DependencyTransientError) as raised:
        await store.get(OWNER, "c1", now=T0)
    assert raised.value.reason == "conversation_store_unavailable"
    assert "boom" not in str(raised.value)
