"""Provider-neutral request and event types for model adapters (PRP-19 item 3).

The orchestrator hands an adapter a :class:`ModelRequest` (system instructions, redacted turns,
the tool manifest, prior tool results as ``tool`` turns) and consumes a stream of
:data:`ModelEvent` values. Every adapter emits the same normalized events for the same
conversation: that is the "action contract".

Nothing here carries scope. ``domain_id``/``customer_id`` are server-derived ``IdentityScope``
facts: a tool manifest that declares such a parameter is refused, and any such value the model
invents in tool-call arguments is the orchestrator's to ignore and log.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# Parameter names a model must never be offered or asked to supply (case-insensitive).
SCOPE_FIELD_NAMES = frozenset(
    {"domain_id", "customer_id", "tenant_id", "identity_scope", "scope", "scope_hash"}
)

StopReason = Literal["end_turn", "tool_calls", "length", "content_filter"]


def _scope_fields_in(schema: Any, path: str = "") -> list[str]:
    """Paths of declared properties (any depth) whose name is a scope field."""
    found: list[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():  # pyright: ignore[reportUnknownVariableType]
            child = f"{path}/{key}"
            if key == "properties" and isinstance(value, dict):
                found.extend(
                    f"{child}/{name}"
                    for name in value  # pyright: ignore[reportUnknownVariableType]
                    if str(name).lower() in SCOPE_FIELD_NAMES  # pyright: ignore[reportUnknownArgumentType]
                )
            found.extend(_scope_fields_in(value, child))
    elif isinstance(schema, list):
        for index, item in enumerate(schema):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            found.extend(_scope_fields_in(item, f"{path}/{index}"))
    return found


class ToolSpec(BaseModel):
    """One tool in the manifest: name, description and the JSON schema of its arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    description: str = Field(max_length=1024)
    parameters: dict[str, Any]

    @field_validator("parameters")
    @classmethod
    def _no_scope_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        offenders = _scope_fields_in(value)
        if offenders:
            raise ValueError(f"tool manifests must not declare scope fields: {offenders}")
        return value


class ToolCallRequest(BaseModel):
    """A tool call the model made on an earlier turn (replayed so results line up)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1, max_length=128)
    tool_name: str
    arguments: dict[str, Any]


class ConversationTurn(BaseModel):
    """One redacted conversation turn.

    ``tool`` turns carry a prior tool result (``tool_call_id`` links it to the call);
    ``assistant`` turns may carry the ``tool_calls`` the model made.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None

    @field_validator("tool_calls")
    @classmethod
    def _assistant_only(
        cls, value: tuple[ToolCallRequest, ...], info: ValidationInfo
    ) -> tuple[ToolCallRequest, ...]:
        if value and info.data.get("role") != "assistant":
            raise ValueError("only assistant turns carry tool_calls")
        return value


class ModelRequest(BaseModel):
    """Everything an adapter needs for one model invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str
    turns: tuple[ConversationTurn, ...] = Field(min_length=1)
    tools: tuple[ToolSpec, ...] = ()
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    correlation_id: str = Field(default="copilot", min_length=1, max_length=128)

    @field_validator("tools")
    @classmethod
    def _unique_tool_names(cls, value: tuple[ToolSpec, ...]) -> tuple[ToolSpec, ...]:
        names = [t.name for t in value]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        return value


class Usage(BaseModel):
    """Token usage as reported by the provider; ``None`` means not reported (never 0)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class TextDelta(BaseModel):
    """A streamed fragment of answer text (the first one marks first-token time)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallRequested(BaseModel):
    """The model asks for an allowlisted tool; ``arguments`` are raw and unvalidated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["tool_call"] = "tool_call"
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ActionSuggestion(BaseModel):
    """The model proposes an action. This is a draft hint only: chat never executes it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["action_suggestion"] = "action_suggestion"
    call_id: str
    action_type: str
    target_ref: str
    rationale: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {})


class Completed(BaseModel):
    """Final event: why the stream stopped, plus provider-reported usage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["completed"] = "completed"
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)


ModelEvent = Annotated[
    TextDelta | ToolCallRequested | ActionSuggestion | Completed,
    Field(discriminator="type"),
]
