"""Conversation flows over the store and the turn engine (PRP-19 item 2).

Conversations belong to one user. The owner key is the caller's pseudonymous principal id taken
from the derived scope, and every store call carries it, so another user's conversation is
indistinguishable from a missing one (404). What is stored is redacted: person pseudonyms, no
secret- or PII-shaped text, and for an assistant turn that was not an answer no text at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from neurosphere_core.copilot.models import ConversationTurn
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.copilot.context import resolve_context
from neurosphere_api.copilot.dependencies import CopilotRuntime
from neurosphere_api.copilot.drafter import ActionPlaneDrafter
from neurosphere_api.copilot.engine import TurnOutcome
from neurosphere_api.copilot.models import (
    CitationView,
    ConversationCreated,
    ConversationList,
    ConversationSummary,
    ConversationView,
    MessageBody,
    SseEvent,
    TurnView,
)
from neurosphere_api.copilot.redaction import redact_for_storage, redact_mapping_for_storage
from neurosphere_api.copilot.store import (
    StoredConversation,
    StoredTurn,
    format_timestamp,
)

__all__ = ["ConversationService", "owner_of"]


def owner_of(scope: IdentityScope) -> str:
    """The conversation owner: the caller's pseudonymous principal id (never a directory id)."""
    return scope.to_contract().principal.principal_id.root


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


def _summary(conversation: StoredConversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        created_at=format_timestamp(conversation.created_at),
        updated_at=format_timestamp(conversation.updated_at),
        retention_class=conversation.retention_class,
        expires_at=format_timestamp(conversation.expires_at),
    )


def _turn_view(turn: StoredTurn) -> TurnView:
    return TurnView(
        message_id=turn.message_id,
        role=turn.role,
        text=turn.text,
        status=turn.status,
        reason_code=turn.reason_code,
        citations=[CitationView.model_validate(dict(c)) for c in turn.citations],
        created_at=format_timestamp(turn.created_at),
        retention_class=turn.retention_class,
        expires_at=format_timestamp(turn.expires_at),
    )


def _history(turns: list[StoredTurn]) -> list[ConversationTurn]:
    """Replay only user messages that received an answer, with that answer.

    A refused, abstained or failed turn leaves no assistant text, so it never re-enters the
    model's context (and an injection that was refused once is not replayed).
    """
    out: list[ConversationTurn] = []
    pending: StoredTurn | None = None
    for turn in turns:
        if turn.role == "user":
            pending = turn
        elif turn.status == "answered" and pending is not None and turn.text:
            out.append(ConversationTurn(role="user", content=pending.text))
            out.append(ConversationTurn(role="assistant", content=turn.text))
            pending = None
        else:
            pending = None
    return out


class ConversationService:
    def __init__(self, runtime: CopilotRuntime) -> None:
        self._rt = runtime

    # -- conversations --------------------------------------------------------------------------

    async def create(self, scope: IdentityScope) -> ConversationCreated:
        rt = self._rt
        now = rt.now()
        retention_class = rt.settings.default_retention_class
        conversation = StoredConversation(
            id=str(uuid4()),
            owner=owner_of(scope),
            created_at=now,
            updated_at=now,
            retention_class=retention_class,
            expires_at=now + rt.settings.ttl_for(retention_class),
        )
        await rt.store.create(conversation)
        return ConversationCreated(
            id=conversation.id,
            created_at=format_timestamp(conversation.created_at),
            retention_class=retention_class,
            expires_at=format_timestamp(conversation.expires_at),
        )

    async def list(
        self, scope: IdentityScope, *, cursor: str | None, limit: int
    ) -> ConversationList:
        rt = self._rt
        limit = max(1, min(limit, rt.settings.max_page_size))
        items, next_cursor = await rt.store.list_conversations(
            owner_of(scope), cursor=cursor, limit=limit, now=rt.now()
        )
        return ConversationList(items=[_summary(c) for c in items], next_cursor=next_cursor)

    async def get(self, scope: IdentityScope, conversation_id: str) -> ConversationView:
        rt = self._rt
        owner, now = owner_of(scope), rt.now()
        conversation = await rt.store.get(owner, conversation_id, now=now)
        if conversation is None:
            raise _not_found()
        turns = await rt.store.load_turns(owner, conversation_id, limit=None, now=now)
        return ConversationView(
            **_summary(conversation).model_dump(), turns=[_turn_view(t) for t in turns]
        )

    async def delete(self, scope: IdentityScope, conversation_id: str) -> None:
        if not await self._rt.store.delete(owner_of(scope), conversation_id):
            raise _not_found()

    # -- messages -------------------------------------------------------------------------------

    async def message(
        self,
        scope: IdentityScope,
        conversation_id: str,
        body: MessageBody,
        *,
        plane: ActionPlane | None,
        correlation_id: str,
    ) -> AsyncIterator[SseEvent]:
        """Validate and prepare the turn (errors here are ordinary HTTP errors), then return the
        event stream. Nothing is streamed or stored until preparation succeeded."""
        rt = self._rt
        settings = rt.settings
        owner, now = owner_of(scope), rt.now()
        conversation = await rt.store.get(owner, conversation_id, now=now)
        if conversation is None:
            raise _not_found()
        if len(body.text) > settings.max_text_chars:
            raise InvalidSchemaError("message is too long", reason="message_too_long")
        context = await resolve_context(
            scope,
            body.context,
            catalog=rt.engine.ports.catalog,
            settings=settings,
            now=now,
        )
        stored = await rt.store.load_turns(
            owner, conversation_id, limit=settings.history_turns, now=now
        )
        history = _history(stored)
        drafter = ActionPlaneDrafter(plane, correlation_id)
        started = now
        key, cap = settings.pseudonym_key, settings.max_text_chars

        async def persist(outcome: TurnOutcome) -> None:
            ended = max(rt.now(), started + timedelta(milliseconds=1))
            ttl = settings.ttl_for(conversation.retention_class)
            user = StoredTurn(
                message_id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                text=redact_for_storage(body.text, key=key, max_chars=cap),
                status=None,
                reason_code=None,
                citations=(),
                context=redact_mapping_for_storage(
                    context.event().model_dump(mode="json", by_alias=True), key=key, max_chars=cap
                ),
                created_at=started,
                retention_class=conversation.retention_class,
                expires_at=started + ttl,
            )
            assistant = StoredTurn(
                message_id=outcome.message_id,
                conversation_id=conversation_id,
                role="assistant",
                text=redact_for_storage(outcome.text, key=key, max_chars=cap),
                status=outcome.status,
                reason_code=outcome.reason_code,
                citations=tuple(c.model_dump() for c in outcome.citations),
                context=None,
                created_at=ended,
                retention_class=conversation.retention_class,
                expires_at=ended + ttl,
            )
            if not await rt.store.append(owner, conversation_id, [user, assistant], now=ended):
                raise _not_found()

        return rt.engine.run(
            scope=scope,
            user_text=body.text,
            context=context,
            history=history,
            drafter=drafter,
            correlation_id=correlation_id,
            persist=persist,
        )
