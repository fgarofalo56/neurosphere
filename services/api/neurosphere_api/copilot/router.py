"""Copilot routes (PRP-19 item 2), mounted at ``/api/v1/copilot``.

| Method | Path                                  | Permission  |
|--------|---------------------------------------|-------------|
| POST   | ``/conversations``                    | ``data.read`` |
| GET    | ``/conversations``                    | ``data.read`` |
| GET    | ``/conversations/{id}``               | ``data.read`` |
| DELETE | ``/conversations/{id}``               | ``data.read`` |
| POST   | ``/conversations/{id}/messages``      | ``data.read`` |

Asking requires ``data.read`` in at least one domain (PRP-19 D5); the tools recheck their own
permission per call. Conversations are user-scoped: the owner comes from the derived scope, never
from the path, and another user's id is a 404. The message route returns ``text/event-stream``
(see :mod:`neurosphere_api.copilot.models` for the event shapes). Preparation errors (404, 403,
422, 503) are ordinary problem responses sent before the stream starts; once streaming, every
failure is an ``error`` event.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.authz import require
from neurosphere_api.copilot.dependencies import (
    CopilotRuntime,
    get_copilot,
    get_optional_action_plane,
)
from neurosphere_api.copilot.models import (
    ConversationCreated,
    ConversationList,
    ConversationView,
    MessageBody,
    SseEvent,
)
from neurosphere_api.copilot.service import ConversationService
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/copilot"

AskScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
Runtime = Annotated[CopilotRuntime, Depends(get_copilot)]
OptionalPlane = Annotated[ActionPlane | None, Depends(get_optional_action_plane)]
ConversationId = Annotated[str, Path(min_length=1, max_length=64)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=256)]
PageLimit = Annotated[int, Query(ge=1, le=100)]

_STREAM_HEADERS: Final = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


async def _encode(events: AsyncIterator[SseEvent]) -> AsyncIterator[bytes]:
    try:
        async for event in events:
            yield event.encode()
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()


def build_router() -> APIRouter:
    router = APIRouter(tags=["copilot"])

    @router.post(
        "/conversations", response_model=ConversationCreated, status_code=status.HTTP_201_CREATED
    )
    async def create_conversation(scope: AskScope, runtime: Runtime) -> ConversationCreated:
        return await ConversationService(runtime).create(scope)

    @router.get("/conversations", response_model=ConversationList)
    async def list_conversations(
        scope: AskScope, runtime: Runtime, cursor: Cursor = None, limit: PageLimit = 20
    ) -> ConversationList:
        return await ConversationService(runtime).list(scope, cursor=cursor, limit=limit)

    @router.get("/conversations/{conversation_id}", response_model=ConversationView)
    async def get_conversation(
        conversation_id: ConversationId, scope: AskScope, runtime: Runtime
    ) -> ConversationView:
        return await ConversationService(runtime).get(scope, conversation_id)

    @router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_conversation(
        conversation_id: ConversationId, scope: AskScope, runtime: Runtime
    ) -> Response:
        await ConversationService(runtime).delete(scope, conversation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/conversations/{conversation_id}/messages",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream"}},
    )
    async def post_message(
        request: Request,
        conversation_id: ConversationId,
        body: MessageBody,
        scope: AskScope,
        runtime: Runtime,
        plane: OptionalPlane,
    ) -> StreamingResponse:
        correlation = audit_correlation_id(correlation_id_of(request.scope))
        events = await ConversationService(runtime).message(
            scope, conversation_id, body, plane=plane, correlation_id=correlation
        )
        return StreamingResponse(
            _encode(events), media_type="text/event-stream", headers=_STREAM_HEADERS
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
