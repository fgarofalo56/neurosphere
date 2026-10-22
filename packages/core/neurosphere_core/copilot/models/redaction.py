"""Outbound redaction: nothing PII- or secret-shaped leaves the boundary in a prompt.

The orchestrator pseudonymizes people before it builds a request; this is the adapter-side
backstop, applied to every string the adapter would serialize (system text, turns, tool-call
arguments, tool descriptions). It is deliberately conservative: GUIDs (directory object ids)
are replaced too. Replacement markers are fixed words, never derived from the matched value.
"""

from __future__ import annotations

import re
from typing import Any, Final

from neurosphere_core.copilot.models.types import (
    ConversationTurn,
    ModelRequest,
    ToolCallRequest,
    ToolSpec,
)

_RULES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
        "[private-key]",
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?"), "[token]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "[token]"),
    (
        re.compile(
            r"(?i)\b(accountkey|sharedaccesskey|sharedaccesssignature|password|pwd|sig"
            r"|api[-_]?key|client[-_]?secret|secret)\s*[=:]\s*\S+"
        ),
        "[credential]",
    ),
    (re.compile(r"\b(?:sk|pk|ghp|gho|xox[bap])[-_][A-Za-z0-9_-]{16,}\b"), "[credential]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[credential]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[id]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]"),
    # Long opaque runs (hex / base64-ish key material).
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}"), "[credential]"),
)


def redact_text(text: str) -> str:
    """Replace PII- and secret-shaped substrings with fixed markers."""
    for pattern, marker in _RULES:
        text = pattern.sub(marker, text)
    return text


def redact_value(value: Any) -> Any:
    """Redact every string leaf of a JSON-like value (dict keys are structure, kept)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def _redact_turn(turn: ConversationTurn) -> ConversationTurn:
    return turn.model_copy(
        update={
            "content": redact_text(turn.content),
            "tool_calls": tuple(
                ToolCallRequest(
                    call_id=c.call_id,
                    tool_name=c.tool_name,
                    arguments=redact_value(c.arguments),
                )
                for c in turn.tool_calls
            ),
        }
    )


def redact_request(request: ModelRequest) -> ModelRequest:
    """A copy of ``request`` that is safe to serialize onto the wire."""
    return request.model_copy(
        update={
            "system": redact_text(request.system),
            "turns": tuple(_redact_turn(t) for t in request.turns),
            "tools": tuple(
                ToolSpec(
                    name=t.name,
                    description=redact_text(t.description),
                    parameters=redact_value(t.parameters),
                )
                for t in request.tools
            ),
        }
    )
