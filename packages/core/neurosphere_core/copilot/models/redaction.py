"""Outbound redaction: nothing PII- or secret-shaped leaves the boundary in a prompt.

The orchestrator pseudonymizes people before it builds a request; this is the adapter-side
backstop, applied to every string the adapter would serialize (system text, turns, tool-call
arguments, tool descriptions). It is deliberately conservative: GUIDs (directory object ids)
are replaced too. Replacement markers are fixed words, never derived from the matched value.

Masked: tokens, keys, credential phrasing (``password is X``, ``pwd=X``, ``pin is 1234``,
generic ``*token*/*secret*/*password*/*api_key* = value``; the label is kept, the value masked),
emails, GUIDs, SSNs, phone numbers (US formats and E.164), street addresses (house number,
street name, bounded suffix list) and card-like digit runs.

Wire identifiers: ``tool_call_id`` / ``call_id`` must be opaque tokens
(``[A-Za-z0-9_.:-]{1,128}``); anything else is replaced by a deterministic hash-derived id (the
same input always maps to the same id, so call/result pairing survives) rather than failing the
turn. ``tool_name`` is never redacted (that would break function calling); it is validated
against the registered tool-name pattern and a mismatch raises ``ValueError``.

Known limit: person names are NOT detected (there is no NER here). People are pseudonymized by
the orchestrator before the request is built; this module cannot catch a free-text name.
"""

from __future__ import annotations

import hashlib
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
    # Credential phrasing: keep the label, mask the value. Explicit labels also accept "is".
    (
        re.compile(
            r"(?i)\b(account[-_]?key|shared[-_]?access[-_]?key|sharedaccesssignature|sig"
            r"|password|passwd|pwd|passcode|pin|api[-_ ]?key|client[-_ ]?secret|secret)"
            r"([\"']?(?:\s*[=:]\s*|\s+is\s+))(?![\[\s])(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1\2[credential]",
    ),
    (re.compile(r"(?i)\b(passcode)(\s+)(?![\[\s]|is\b)(\S+)"), r"\1\2[credential]"),
    # Generic key=value / key: value where the key names a secret ("max_tokens" is not one).
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.-]*(?:token|secret|password|apikey|api_key)"
            r"(?![_.-]?(?:count|limit|usage|budget|used|total|max|min)\b)"
            r"(?:[_.-][A-Za-z0-9_.-]*)?[\"']?\s*[=:]\s*)(?![\[\s])(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1[credential]",
    ),
    (re.compile(r"\b(?:sk|pk|ghp|gho|xox[bap])[-_][A-Za-z0-9_-]{16,}\b"), "[credential]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[credential]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[id]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    # Phones: E.164 needs a leading "+", US formats need separators, so dates (2025-04-14),
    # versions (1.1.0), SSNs (3-2-4) and plain counts never match. Runs before the card rule.
    (re.compile(r"(?<![\w+])\+\d{8,15}\b"), "[phone]"),
    (
        re.compile(r"(?<![\w.-])(?:\+1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}\b"),
        "[phone]",
    ),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]"),
    (
        re.compile(
            r"(?i)\b\d{1,6}\s+(?:(?:[a-z][a-z'.-]*|\d+(?:st|nd|rd|th))\s+){1,4}?"
            r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|dr|drive|ct|court|way"
            r"|pl|place|pkwy|hwy)\b\.?"
        ),
        "[address]",
    ),
    # Long opaque runs (hex / base64-ish key material).
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}"), "[credential]"),
)


_SAFE_CALL_ID: Final = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_TOOL_NAME: Final = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def safe_call_id(call_id: str) -> str:
    """The id itself when opaque-token shaped, else a deterministic hash-derived id."""
    if _SAFE_CALL_ID.fullmatch(call_id):
        return call_id
    return "call_" + hashlib.sha256(call_id.encode("utf-8")).hexdigest()[:32]


def _checked_tool_name(name: str) -> str:
    if not _TOOL_NAME.fullmatch(name):
        raise ValueError("tool_name does not match the registered tool-name pattern")
    return name


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
            "tool_call_id": None if turn.tool_call_id is None else safe_call_id(turn.tool_call_id),
            "tool_calls": tuple(
                ToolCallRequest(
                    call_id=safe_call_id(c.call_id),
                    tool_name=_checked_tool_name(c.tool_name),
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
