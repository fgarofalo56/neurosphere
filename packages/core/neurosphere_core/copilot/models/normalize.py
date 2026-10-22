"""The action contract: how raw provider tool calls become normalized events.

Every adapter funnels tool calls through :func:`normalize_tool_call` and stop reasons through
:func:`stop_reason_for`, so the same model decision yields identical events whichever
provider produced it.

``suggest_action`` is the one reserved tool name. A call to it whose arguments match
:class:`SuggestActionArgs` becomes an :class:`ActionSuggestion` (a draft hint for the PRP-17
confirmation dialog); anything else is a plain :class:`ToolCallRequested` that the orchestrator
checks against its allowlist. The adapter never decides what is allowed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurosphere_core.copilot.models.types import (
    ActionSuggestion,
    ModelEvent,
    StopReason,
    TextDelta,
    ToolCallRequested,
)
from neurosphere_core.errors import DependencyTransientError

SUGGEST_ACTION_TOOL: Final = "suggest_action"

_STOP_REASONS: Final[dict[str, StopReason]] = {
    "stop": "end_turn",
    "completed": "end_turn",
    "end_turn": "end_turn",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "length": "length",
    "max_output_tokens": "length",
    "content_filter": "content_filter",
}


class SuggestActionArgs(BaseModel):
    """Arguments of the reserved ``suggest_action`` tool."""

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=128)
    target_ref: str = Field(min_length=1, max_length=512)
    rationale: str = Field(default="", max_length=2000)
    parameters: dict[str, Any] = Field(default_factory=lambda: {})


def invalid_response(detail: str) -> DependencyTransientError:
    """The provider returned something we cannot normalize (HTTP 502)."""
    return DependencyTransientError(detail, reason="model_response_invalid", upstream_invalid=True)


def parse_arguments(raw: str) -> dict[str, Any]:
    """Tool-call arguments arrive as a JSON string; they must be a JSON object."""
    try:
        parsed: Any = json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise invalid_response("tool-call arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise invalid_response("tool-call arguments are not a JSON object")
    return parsed  # pyright: ignore[reportUnknownVariableType]


def normalize_tool_call(
    call_id: str, tool_name: str, arguments_json: str
) -> ToolCallRequested | ActionSuggestion:
    """Normalize one provider tool call (raw JSON argument string)."""
    arguments = parse_arguments(arguments_json)
    if tool_name == SUGGEST_ACTION_TOOL:
        try:
            args = SuggestActionArgs.model_validate(arguments)
        except ValidationError:
            return ToolCallRequested(call_id=call_id, tool_name=tool_name, arguments=arguments)
        return ActionSuggestion(
            call_id=call_id,
            action_type=args.action_type,
            target_ref=args.target_ref,
            rationale=args.rationale,
            parameters=args.parameters,
        )
    return ToolCallRequested(call_id=call_id, tool_name=tool_name, arguments=arguments)


def stop_reason_for(raw: str | None, *, saw_tool_calls: bool) -> StopReason:
    """Normalize a provider finish reason; any emitted tool call means ``tool_calls``."""
    if saw_tool_calls:
        return "tool_calls"
    if raw is None:
        raise invalid_response("stream ended without a finish reason")
    try:
        return _STOP_REASONS[raw]
    except KeyError:
        raise invalid_response("unrecognized finish reason") from None


def collapse_text(events: Iterable[ModelEvent]) -> list[ModelEvent]:
    """Merge consecutive text deltas so streams with different chunking compare equal."""
    out: list[ModelEvent] = []
    for event in events:
        previous = out[-1] if out else None
        if isinstance(event, TextDelta) and isinstance(previous, TextDelta):
            out[-1] = TextDelta(text=previous.text + event.text)
        else:
            out.append(event)
    return out
