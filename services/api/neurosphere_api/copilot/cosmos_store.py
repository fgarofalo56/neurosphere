"""Cosmos NoSQL conversation store (azure-cosmos aio, PRP-19 item 2).

Container: partition key ``/owner`` (the caller's pseudonymous principal id), default TTL enabled
(``-1``) so each document's own ``ttl`` applies. Documents in one owner partition:

* ``doc_type = conversation``, ``id = <conversation id>``, ``ttl`` = seconds until the latest
  turn expires (refreshed on append);
* ``doc_type = turn``, ``id = <message id>``, ``conversation_id``, ``ttl`` = seconds until THAT
  turn's ``expires_at`` (per-turn retention).

Every read is partition-scoped to the owner, so another user's id reads as absent. Queries are
parameterized with fixed field names. Outages -> ``dependency_transient``
(``conversation_store_unavailable``); 429 -> ``rate_limited``. Messages never echo SDK text or
stored documents. Provision with :func:`create_conversation_container` (item 7 / infra).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, NoReturn

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, RateLimitedError

from neurosphere_api.copilot.store import (
    StoredConversation,
    StoredTurn,
    decode_cursor,
    encode_cursor,
)

__all__ = [
    "DEFAULT_CONVERSATION_CONTAINER",
    "PARTITION_KEY_PATH",
    "CosmosConversationStore",
    "create_conversation_container",
]

DEFAULT_CONVERSATION_CONTAINER: Final = "copilot_conversations"
PARTITION_KEY_PATH: Final = "/owner"
_SORT_END: Final = chr(0xFFFF)  # sorts after every sort_key (ISO timestamp + id)


async def create_conversation_container(
    database: DatabaseProxy, container_id: str = DEFAULT_CONVERSATION_CONTAINER
) -> ContainerProxy:
    """Create (or open) the container: partition key ``/owner``, per-document TTL enabled."""
    return await database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=PARTITION_KEY_PATH), default_ttl=-1
    )


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "conversation store is unavailable", reason="conversation_store_unavailable"
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "conversation store throttled the request") from exc
    raise _unavailable() from exc


def _ttl_seconds(expires_at: datetime, now: datetime) -> int:
    return max(1, int((expires_at - now).total_seconds()))


class CosmosConversationStore:
    """:class:`~neurosphere_api.copilot.store.ConversationStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_CONVERSATION_CONTAINER,
    ) -> CosmosConversationStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def _read_conversation(self, owner: str, conversation_id: str) -> dict[str, Any] | None:
        try:
            row = await self._container.read_item(item=conversation_id, partition_key=owner)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != "conversation" or row.get("owner") != owner:
            return None
        return dict(row)

    async def _query(
        self, owner: str, query: str, parameters: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        try:
            return [
                dict(row)
                async for row in self._container.query_items(
                    query=query, parameters=parameters, partition_key=owner
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)

    async def create(self, conversation: StoredConversation) -> None:
        body = conversation.to_document()
        body["ttl"] = _ttl_seconds(conversation.expires_at, conversation.created_at)
        try:
            await self._container.create_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)

    async def get(
        self, owner: str, conversation_id: str, *, now: datetime
    ) -> StoredConversation | None:
        row = await self._read_conversation(owner, conversation_id)
        if row is None:
            return None
        found = StoredConversation.from_document(row)
        return found if found.expires_at > now else None

    async def list_conversations(
        self, owner: str, *, cursor: str | None, limit: int, now: datetime
    ) -> tuple[list[StoredConversation], str | None]:
        after = _SORT_END if cursor is None else decode_cursor(cursor)
        rows = await self._query(
            owner,
            "SELECT * FROM c WHERE c.doc_type = 'conversation' AND c.owner = @owner "
            "AND c.sort_key < @after ORDER BY c.sort_key DESC",
            [
                {"name": "@owner", "value": owner},
                {"name": "@after", "value": after},
            ],
        )
        live = [
            c for c in (StoredConversation.from_document(r) for r in rows) if c.expires_at > now
        ]
        page = live[:limit]
        more = len(live) > limit
        return page, encode_cursor(page[-1].sort_key) if more and page else None

    async def append(
        self, owner: str, conversation_id: str, turns: Sequence[StoredTurn], *, now: datetime
    ) -> bool:
        row = await self._read_conversation(owner, conversation_id)
        if row is None:
            return False
        conversation = StoredConversation.from_document(row)
        if conversation.expires_at <= now:
            return False
        try:
            for turn in turns:
                body = turn.to_document(owner)
                body["ttl"] = _ttl_seconds(turn.expires_at, now)
                await self._container.create_item(body=body)
            newest = max([conversation.expires_at, *(t.expires_at for t in turns)])
            updated = StoredConversation(
                id=conversation.id,
                owner=owner,
                created_at=conversation.created_at,
                updated_at=now,
                retention_class=conversation.retention_class,
                expires_at=newest,
            ).to_document()
            updated["ttl"] = _ttl_seconds(newest, now)
            await self._container.upsert_item(body=updated)
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def load_turns(
        self, owner: str, conversation_id: str, *, limit: int | None, now: datetime
    ) -> list[StoredTurn]:
        rows = await self._query(
            owner,
            "SELECT * FROM c WHERE c.doc_type = 'turn' AND c.owner = @owner "
            "AND c.conversation_id = @conversation ORDER BY c.sort_key ASC",
            [
                {"name": "@owner", "value": owner},
                {"name": "@conversation", "value": conversation_id},
            ],
        )
        live = [t for t in (StoredTurn.from_document(r) for r in rows) if t.expires_at > now]
        return live if limit is None else live[-limit:]

    async def delete(self, owner: str, conversation_id: str) -> bool:
        if await self._read_conversation(owner, conversation_id) is None:
            return False
        rows = await self._query(
            owner,
            "SELECT c.id FROM c WHERE c.conversation_id = @conversation AND c.owner = @owner",
            [
                {"name": "@owner", "value": owner},
                {"name": "@conversation", "value": conversation_id},
            ],
        )
        try:
            for row in rows:
                await self._container.delete_item(item=row["id"], partition_key=owner)
            await self._container.delete_item(item=conversation_id, partition_key=owner)
        except CosmosResourceNotFoundError:
            return True
        except Exception as exc:
            _raise_mapped(exc)
        return True
