"""Wire models of the copilot API (PRP-19 wire contract, decided 2026-10-21).

Requests: ``MessageBody`` (text plus a context hint). Responses: the conversation views and the
SSE event payloads. Every model forbids extra members. Event payloads are the exact shapes the
chat UI (item 6) and the mock API (item 7) code against.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

__all__ = [
    "AbstainEvent",
    "ActionSuggestionEvent",
    "ChartEvent",
    "CitationEvent",
    "ContextEvent",
    "ConversationCreated",
    "ConversationList",
    "ConversationSummary",
    "ConversationView",
    "DeniedEvent",
    "DoneEvent",
    "ErrorEvent",
    "MessageBody",
    "MessageContext",
    "SseEvent",
    "TimeRange",
    "TokenEvent",
    "ToolEvent",
    "TurnView",
]

ShortText = Annotated[str, StringConstraints(max_length=128)]
FilterValue = ShortText | Annotated[list[ShortText], Field(max_length=10)]
EntityId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Freshness = Literal["fresh", "stale", "unknown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TimeRange(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: Annotated[str, Field(alias="from", max_length=40)]
    to: Annotated[str, Field(max_length=40)]

    @model_validator(mode="after")
    def _ordered(self) -> TimeRange:
        try:
            start, end = _parse(self.from_), _parse(self.to)
        except ValueError:
            raise ValueError("time_range bounds must be ISO 8601 timestamps") from None
        if start.tzinfo is None or end.tzinfo is None or start > end:
            raise ValueError("time_range must be an ordered, timezone-aware interval")
        return self


class MessageContext(_Model):
    """What the UI shows the user right now. A hint that can only narrow the derived scope."""

    page: ShortText | None = None
    route: Annotated[str | None, StringConstraints(max_length=256)] = None
    filters: dict[ShortText, FilterValue] = Field(default_factory=dict[str, FilterValue])
    time_range: TimeRange | None = None
    selection: Annotated[list[EntityId], Field(max_length=100)] = Field(default_factory=list[str])
    domain_id: Annotated[str | None, StringConstraints(max_length=512)] = None

    @field_validator("filters")
    @classmethod
    def _bounded(cls, value: dict[str, FilterValue]) -> dict[str, FilterValue]:
        if len(value) > 16:
            raise ValueError("too many filters")
        return value


class MessageBody(_Model):
    text: Annotated[str, StringConstraints(min_length=1, max_length=8000)]
    context: MessageContext = Field(default_factory=MessageContext)


# -- conversation views -------------------------------------------------------------------------


class ConversationCreated(_Model):
    id: str
    created_at: str
    retention_class: str
    expires_at: str


class CitationView(_Model):
    record_id: str
    kind: str
    source: str
    as_of: str | None
    freshness: Freshness


class TurnView(_Model):
    message_id: str
    role: Literal["user", "assistant"]
    text: str
    status: Literal["answered", "abstain", "denied", "error"] | None
    reason_code: str | None
    citations: list[CitationView]
    created_at: str
    retention_class: str
    expires_at: str


class ConversationSummary(_Model):
    id: str
    created_at: str
    updated_at: str
    retention_class: str
    expires_at: str


class ConversationView(ConversationSummary):
    turns: list[TurnView]


class ConversationList(_Model):
    items: list[ConversationSummary]
    next_cursor: str | None


# -- SSE event payloads -------------------------------------------------------------------------


class ContextEvent(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    page: str | None
    route: str | None
    filters: dict[str, FilterValue]
    time_range: TimeRange | None
    selection: list[str]
    dropped_selection_count: int
    applied_domains: list[str]


class ToolEvent(_Model):
    name: str
    status: Literal["started", "ok", "refused"]


class TokenEvent(_Model):
    text: str


class CitationEvent(CitationView):
    pass


class ChartEvent(_Model):
    chart_plan: dict[str, object]


class ActionSuggestionEvent(_Model):
    intent_id: str
    domain_id: str
    action_type: str
    target: dict[str, object]
    intent_hash: str


class DoneEvent(_Model):
    message_id: str
    status: Literal["answered"] = "answered"


class AbstainEvent(_Model):
    message_id: str
    reason_code: str
    reason: str


class DeniedEvent(_Model):
    message_id: str
    reason_code: str
    reason: str


class ErrorEvent(_Model):
    code: str
    detail: str


EventPayload = (
    ContextEvent
    | ToolEvent
    | TokenEvent
    | CitationEvent
    | ChartEvent
    | ActionSuggestionEvent
    | DoneEvent
    | AbstainEvent
    | DeniedEvent
    | ErrorEvent
)

TERMINAL_EVENTS = frozenset({"done", "abstain", "denied", "error"})


class SseEvent(BaseModel):
    """One server-sent event: the ``event:`` name and its typed payload."""

    model_config = ConfigDict(frozen=True)

    name: Literal[
        "context",
        "tool",
        "token",
        "citation",
        "chart",
        "action_suggestion",
        "done",
        "abstain",
        "denied",
        "error",
    ]
    payload: EventPayload

    def encode(self) -> bytes:
        data = json.dumps(
            self.payload.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return f"event: {self.name}\ndata: {data}\n\n".encode()

    @property
    def terminal(self) -> bool:
        return self.name in TERMINAL_EVENTS
