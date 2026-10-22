"""Conversation persistence port and the in-memory implementation (PRP-19 item 2).

Conversations are user-scoped: every call carries the ``owner`` (the caller's pseudonymous
principal id) and a lookup that does not match the owner finds nothing, exactly like an unknown
id, so another user's conversation is a 404 and never a 403. Only redacted text is stored (see
``redaction.py``); each turn carries its retention class and ``expires_at``. Expired turns and
conversations are invisible to every read whether or not the platform has removed them yet.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol, runtime_checkable

from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "ConversationStore",
    "InMemoryConversationStore",
    "StoredConversation",
    "StoredTurn",
    "TurnStatus",
    "decode_cursor",
    "encode_cursor",
    "format_timestamp",
    "parse_timestamp",
]

TurnStatus = Literal["answered", "abstain", "denied", "error"]
_MAX_CURSOR: Final = 256


def format_timestamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def encode_cursor(sort_key: str) -> str:
    return base64.urlsafe_b64encode(sort_key.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    if len(cursor) > _MAX_CURSOR:
        raise InvalidSchemaError("cursor is invalid", reason="invalid_cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidSchemaError("cursor is invalid", reason="invalid_cursor") from None


@dataclass(frozen=True, slots=True)
class StoredTurn:
    """One redacted turn. ``text`` is empty for an assistant turn that was not an answer."""

    message_id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    text: str
    status: TurnStatus | None
    reason_code: str | None
    citations: tuple[Mapping[str, Any], ...]
    context: Mapping[str, Any] | None
    created_at: datetime
    retention_class: str
    expires_at: datetime

    @property
    def sort_key(self) -> str:
        return f"{format_timestamp(self.created_at)}|{self.message_id}"

    def to_document(self, owner: str) -> dict[str, Any]:
        return {
            "id": self.message_id,
            "doc_type": "turn",
            "owner": owner,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "text": self.text,
            "status": self.status,
            "reason_code": self.reason_code,
            "citations": [dict(c) for c in self.citations],
            "context": None if self.context is None else dict(self.context),
            "created_at": format_timestamp(self.created_at),
            "retention_class": self.retention_class,
            "expires_at": format_timestamp(self.expires_at),
            "sort_key": self.sort_key,
        }

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> StoredTurn:
        return cls(
            message_id=str(doc["id"]),
            conversation_id=str(doc["conversation_id"]),
            role=doc["role"],
            text=str(doc["text"]),
            status=doc.get("status"),
            reason_code=doc.get("reason_code"),
            citations=tuple(doc.get("citations") or ()),
            context=doc.get("context"),
            created_at=parse_timestamp(doc["created_at"]),
            retention_class=str(doc["retention_class"]),
            expires_at=parse_timestamp(doc["expires_at"]),
        )


@dataclass(frozen=True, slots=True)
class StoredConversation:
    id: str
    owner: str
    created_at: datetime
    updated_at: datetime
    retention_class: str
    expires_at: datetime

    @property
    def sort_key(self) -> str:
        return f"{format_timestamp(self.created_at)}|{self.id}"

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_type": "conversation",
            "owner": self.owner,
            "created_at": format_timestamp(self.created_at),
            "updated_at": format_timestamp(self.updated_at),
            "retention_class": self.retention_class,
            "expires_at": format_timestamp(self.expires_at),
            "sort_key": self.sort_key,
        }

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> StoredConversation:
        return cls(
            id=str(doc["id"]),
            owner=str(doc["owner"]),
            created_at=parse_timestamp(doc["created_at"]),
            updated_at=parse_timestamp(doc["updated_at"]),
            retention_class=str(doc["retention_class"]),
            expires_at=parse_timestamp(doc["expires_at"]),
        )


@runtime_checkable
class ConversationStore(Protocol):
    """Owner-partitioned conversation storage. Every method is scoped by ``owner``."""

    async def create(self, conversation: StoredConversation) -> None: ...

    async def get(
        self, owner: str, conversation_id: str, *, now: datetime
    ) -> StoredConversation | None:
        """``None`` when absent, expired, or owned by someone else."""
        ...

    async def list_conversations(
        self, owner: str, *, cursor: str | None, limit: int, now: datetime
    ) -> tuple[list[StoredConversation], str | None]:
        """The owner's live conversations, newest first, with the next cursor (or ``None``)."""
        ...

    async def append(
        self, owner: str, conversation_id: str, turns: Sequence[StoredTurn], *, now: datetime
    ) -> bool:
        """Add turns and extend the conversation's expiry; ``False`` when it is not the owner's."""
        ...

    async def load_turns(
        self, owner: str, conversation_id: str, *, limit: int | None, now: datetime
    ) -> list[StoredTurn]:
        """Live turns oldest first; with ``limit`` the most recent ``limit`` of them."""
        ...

    async def delete(self, owner: str, conversation_id: str) -> bool:
        """Remove the conversation and its turns; ``False`` when it is not the owner's."""
        ...


@dataclass
class InMemoryConversationStore:
    """Process-local store for tests and the local sandbox."""

    _conversations: dict[tuple[str, str], StoredConversation] = field(
        default_factory=dict[tuple[str, str], StoredConversation]
    )
    _turns: dict[tuple[str, str], list[StoredTurn]] = field(
        default_factory=dict[tuple[str, str], list[StoredTurn]]
    )

    async def create(self, conversation: StoredConversation) -> None:
        key = (conversation.owner, conversation.id)
        self._conversations[key] = conversation
        self._turns[key] = []

    async def get(
        self, owner: str, conversation_id: str, *, now: datetime
    ) -> StoredConversation | None:
        found = self._conversations.get((owner, conversation_id))
        return found if found is not None and found.expires_at > now else None

    async def list_conversations(
        self, owner: str, *, cursor: str | None, limit: int, now: datetime
    ) -> tuple[list[StoredConversation], str | None]:
        after = None if cursor is None else decode_cursor(cursor)
        live = sorted(
            (
                c
                for (who, _), c in self._conversations.items()
                if who == owner and c.expires_at > now and (after is None or c.sort_key < after)
            ),
            key=lambda c: c.sort_key,
            reverse=True,
        )
        page = live[:limit]
        more = len(live) > limit
        return page, encode_cursor(page[-1].sort_key) if more and page else None

    async def append(
        self, owner: str, conversation_id: str, turns: Sequence[StoredTurn], *, now: datetime
    ) -> bool:
        key = (owner, conversation_id)
        conversation = self._conversations.get(key)
        if conversation is None or conversation.expires_at <= now:
            return False
        self._turns[key].extend(turns)
        newest = max([conversation.expires_at, *(t.expires_at for t in turns)])
        self._conversations[key] = StoredConversation(
            id=conversation.id,
            owner=conversation.owner,
            created_at=conversation.created_at,
            updated_at=now,
            retention_class=conversation.retention_class,
            expires_at=newest,
        )
        return True

    async def load_turns(
        self, owner: str, conversation_id: str, *, limit: int | None, now: datetime
    ) -> list[StoredTurn]:
        key = (owner, conversation_id)
        if key not in self._conversations:
            return []
        live = sorted((t for t in self._turns[key] if t.expires_at > now), key=lambda t: t.sort_key)
        return live if limit is None else live[-limit:]

    async def delete(self, owner: str, conversation_id: str) -> bool:
        key = (owner, conversation_id)
        if key not in self._conversations:
            return False
        del self._conversations[key]
        del self._turns[key]
        return True

    # -- test visibility: what is physically held (including expired and raw text) -------------

    def raw_documents(self) -> list[dict[str, Any]]:
        docs = [c.to_document() for c in self._conversations.values()]
        for (owner, _), turns in self._turns.items():
            docs.extend(t.to_document(owner) for t in turns)
        return docs
