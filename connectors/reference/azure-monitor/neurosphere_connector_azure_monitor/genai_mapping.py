"""Map GenAI span rows (``APP_GENAI_DEPENDENCIES`` / ``APP_GENAI_REQUESTS``) to ``TelemetryEvent``.

One row of workspace-based Application Insights ``AppDependencies`` or ``AppRequests`` becomes
one event, mirroring the OTLP edge mapping (``ingest/otlp_mapping.py``): ``event_id`` is
``<trace id>:<span id>`` and is the only dedupe key, so re-reading a window is safe.

Rules:
- Metadata only. The templates never select content; this mapper additionally reads only the
  allowlisted columns and attribute keys and ignores every other key on the row.
- An unusable row raises ``GenAiRowSkipped`` with a short ``reason`` code. Nothing is guessed:
  trace and span ids must already be W3C hex (32 and 16), else the row is skipped.
- Missing values are ``None``, never 0. Attribute values arrive as strings (the exporter
  serializes non-string attributes), so token counts are parsed from text.
- ``canonical_agent_id`` is never set; agent identity is the resolver's job (PRP-137).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from pydantic import ValidationError

from neurosphere_connector_azure_monitor.queries import (
    AGENT_ID_ATTRS,
    CACHED_TOKEN_ATTRS,
    INPUT_TOKEN_ATTRS,
    MODEL_ATTRS,
    OPERATION_ATTR,
    OUTPUT_TOKEN_ATTRS,
    PROVIDER_ATTRS,
    REASONING_TOKEN_ATTRS,
)

__all__ = ["GenAiRowSkipped", "map_genai_row"]

_SCHEMA_VERSION: Final = "1.0.0"
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_INT = re.compile(r"^[0-9]+$")

# Copy of the edge's operation table (``_OPERATION_KIND``); unknown operations map to "unknown".
_OPERATION_KIND: Final = {
    "chat": "model_call",
    "text_completion": "model_call",
    "generate_content": "model_call",
    "embeddings": "model_call",
    "execute_tool": "tool_call",
    "invoke_agent": "agent_run",
    "create_agent": "agent_run",
    "retrieval": "retrieval",
}


class GenAiRowSkipped(ValueError):  # noqa: N818 - a skip signal, not an error
    """A row that cannot become an event. ``reason`` is a short code the caller can count by."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _first_text(row: Mapping[str, Any], names: Sequence[str]) -> str | None:
    for name in names:
        text = _text(row, name)
        if text is not None:
            return text
    return None


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value >= 0 and value == int(value) else None
    if isinstance(value, str):
        text = value.strip()
        return int(text) if _INT.fullmatch(text) else None
    return None


def _first_count(row: Mapping[str, Any], names: Sequence[str]) -> int | None:
    for name in names:
        count = _count(row.get(name))
        if count is not None:
            return count
    return None


def _outcome(value: Any) -> Literal["success", "error", "unknown"]:
    if isinstance(value, bool):
        return "success" if value else "error"
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return "success" if value.strip().lower() == "true" else "error"
    return "unknown"


def _duration_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return math.floor(number)


def _time(row: Mapping[str, Any]) -> str:
    raw = row.get("TimeGenerated")
    if not isinstance(raw, str):
        raise GenAiRowSkipped("bad_time")
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GenAiRowSkipped("bad_time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sampling(row: Mapping[str, Any]) -> dict[str, Any] | None:
    items = _count(row.get("ItemCount"))
    if items is None or items <= 1:
        return None
    # The contract has method "unknown"; the source does not say which sampler ran.
    return {"rate": 1.0 / items, "method": "unknown"}


def map_genai_row(
    row: Mapping[str, Any],
    *,
    cloud: Literal["commercial", "government"],
    customer_id: str,
    source_id: str,
    domain_id: str | None = None,
    app_role_names: Sequence[str] | None = None,
) -> TelemetryEvent:
    """Map one GenAI span row; raise ``GenAiRowSkipped`` (with a reason code) when unusable."""
    if app_role_names is not None and _text(row, "AppRoleName") not in app_role_names:
        raise GenAiRowSkipped("role_filtered")
    operation = _text(row, OPERATION_ATTR)
    if operation is None:
        raise GenAiRowSkipped("no_operation")
    trace = (_text(row, "OperationId") or "").lower()
    span = (_text(row, "Id") or "").lower()
    if not (_HEX32.fullmatch(trace) and _HEX16.fullmatch(span)):
        raise GenAiRowSkipped("bad_ids")
    when = _time(row)
    parent = (_text(row, "ParentId") or "").lower()
    tokens = {
        "input": _first_count(row, INPUT_TOKEN_ATTRS),
        "output": _first_count(row, OUTPUT_TOKEN_ATTRS),
        "cached": _first_count(row, CACHED_TOKEN_ATTRS),
        "reasoning": _first_count(row, REASONING_TOKEN_ATTRS),
    }
    data: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "event_id": f"{trace}:{span}",
        "event_time": when,
        "cloud": cloud,
        "customer_id": customer_id,
        "domain_id": domain_id or None,
        "source_id": source_id,
        "external_agent_id": _first_text(row, AGENT_ID_ATTRS),
        "trace_id": trace,
        "span_id": span,
        "parent_span_id": parent if _HEX16.fullmatch(parent) and parent != span else None,
        "span_kind": _OPERATION_KIND.get(operation, "unknown"),
        "provider": _first_text(row, PROVIDER_ATTRS),
        "model": _first_text(row, MODEL_ATTRS),
        "outcome": _outcome(row.get("Success")),
        "duration_ms": _duration_ms(row.get("DurationMs")),
        "token_breakdown": tokens if any(v is not None for v in tokens.values()) else None,
        "sampling": _sampling(row),
    }
    try:
        return TelemetryEvent.model_validate(data)
    except ValidationError as exc:
        raise GenAiRowSkipped("invalid_event") from exc
