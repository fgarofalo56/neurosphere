"""The single OTLP/JSON -> TelemetryEvent mapping module (C14: a documented subset).

Attribute names for models and tokens vary by instrumentation version, so every name lives in
the tables below and nowhere else. A value that is absent or not usable maps to ``None``
(unknown); it is never guessed and never defaulted to 0. First matching name in each tuple wins.

Spans (``resourceSpans[].scopeSpans[].spans[]``), one TelemetryEvent per span:

====================  ===========================================================
TelemetryEvent        source
====================  ===========================================================
event_id              ``f"{traceId}:{spanId}"`` (deterministic, so replay dedupes)
trace_id / span_id    ``traceId`` / ``spanId`` (lowercase hex)
parent_span_id        ``parentSpanId`` (empty -> null)
event_time            ``startTimeUnixNano`` (missing -> span rejected, never guessed)
duration_ms           ``(end - start) // 1e6`` when both set and end >= start, else null
outcome               ``status.code``: OK -> success, ERROR -> error, UNSET -> unknown
span_kind             ``gen_ai.operation.name`` via ``_OPERATION_KIND``, else unknown
provider, model, ...  attribute tables ``PROVIDER_ATTRS`` etc. below
request_id            ``REQUEST_ID_ATTRS``
====================  ===========================================================

Metrics (``resourceMetrics[].scopeMetrics[].metrics[]``): only ``sum`` and ``gauge`` whose metric
name is in ``TOKEN_METRICS`` map; each data point becomes one TelemetryEvent carrying that one
token count. Histograms, exponential histograms, summaries, unknown metric names and non-integer
or negative values are reported as ignored with a reason code, never dropped silently.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from pydantic import ValidationError

from neurosphere_api.ingest.reasons import ReasonCode

SCHEMA_VERSION: Final = "1.0.0"
# Tool, service and MCP identity (F1) exist from schema 1.1.0; events that carry none stay 1.0.0.
SCHEMA_VERSION_IDENTITY: Final = "1.1.0"

# Resource attributes that carry the producer's claims.
CLAIM_CUSTOMER_ATTR: Final = "neurosphere.customer_id"
CLAIM_SOURCE_ATTR: Final = "neurosphere.source_id"
CLAIM_CLOUD_ATTR: Final = "neurosphere.cloud"

PROVIDER_ATTRS: Final = ("gen_ai.provider.name", "gen_ai.system", "llm.provider")
MODEL_ATTRS: Final = (
    "gen_ai.response.model",
    "gen_ai.request.model",
    "llm.model_name",
    "llm.request.model",
)
INPUT_TOKEN_ATTRS: Final = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.prompt_tokens",
    "llm.usage.prompt_tokens",
)
OUTPUT_TOKEN_ATTRS: Final = (
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.completion_tokens",
    "llm.usage.completion_tokens",
)
CACHED_TOKEN_ATTRS: Final = (
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.cached_tokens",
    "llm.usage.cache_read_input_tokens",
)
REASONING_TOKEN_ATTRS: Final = (
    "gen_ai.usage.reasoning.output_tokens",
    "gen_ai.usage.reasoning_tokens",
)
REQUEST_ID_ATTRS: Final = ("neurosphere.request_id", "request_id", "x-request-id")
AGENT_ID_ATTRS: Final = ("gen_ai.agent.id",)
OPERATION_ATTR: Final = "gen_ai.operation.name"

# Tool, service and MCP identity (docs/connectors/verification/otel-genai-tool-service.md).
TOOL_NAME_ATTR: Final = "gen_ai.tool.name"
MCP_METHOD_ATTR: Final = "mcp.method.name"
SERVER_ADDRESS_ATTR: Final = "server.address"
# Called-service sources in precedence order: (name attribute, namespace attribute).
SPAN_SERVICE_ATTRS: Final = (
    ("server.service.name", "server.service.namespace"),
    ("service.peer.name", "service.peer.namespace"),
    ("peer.service", None),
)
RESOURCE_SERVICE_ATTRS: Final = ("service.name", "service.namespace")
TOOL_NAME_MAX: Final = 128
SERVICE_ID_MAX: Final = 256
HOST_MAX: Final = 253
# Conservative identifier: starts alphanumeric, then letters, digits and ``._-/:``. Whitespace,
# ``?``, ``#``, ``@`` and ``%`` never match; ``://`` is rejected explicitly.
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/:]*")
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")

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

# Metric name -> TokenBreakdown field. Sum and gauge data points only.
TOKEN_METRICS: Final = {
    "gen_ai.usage.input_tokens": "input",
    "gen_ai.usage.prompt_tokens": "input",
    "llm.usage.prompt_tokens": "input",
    "gen_ai.usage.output_tokens": "output",
    "gen_ai.usage.completion_tokens": "output",
    "llm.usage.completion_tokens": "output",
    "gen_ai.usage.cached_tokens": "cached",
    "gen_ai.usage.reasoning_tokens": "reasoning",
}
UNSUPPORTED_METRIC_KINDS: Final = ("histogram", "exponentialHistogram", "summary")

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_STATUS_OUTCOME: Final = {
    1: "success",
    2: "error",
    "STATUS_CODE_OK": "success",
    "STATUS_CODE_ERROR": "error",
}


@dataclass(frozen=True)
class Scope:
    """Stamped from the producer registration after claims are verified."""

    cloud: str
    customer_id: str
    source_id: str


@dataclass(frozen=True)
class Claims:
    customer_id: str | None
    source_id: str | None
    cloud: str | None


class MappingError(Exception):
    """One item cannot be mapped; carries the reason code (never the offending value)."""

    def __init__(self, reason: ReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _any_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    return None


def attributes_to_dict(attrs: Any) -> dict[str, Any]:
    """OTLP/JSON ``[{"key", "value": {"stringValue": ...}}]`` -> ``{key: scalar}``."""
    out: dict[str, Any] = {}
    if not isinstance(attrs, Sequence) or isinstance(attrs, str):
        return out
    for item in attrs:
        if isinstance(item, Mapping) and isinstance(item.get("key"), str):
            out.setdefault(item["key"], _any_value(item.get("value")))
    return out


def resource_claims(resource: Any) -> Claims:
    attrs = attributes_to_dict(
        resource.get("attributes") if isinstance(resource, Mapping) else None
    )

    def text(name: str) -> str | None:
        value = attrs.get(name)
        return value if isinstance(value, str) and value else None

    return Claims(text(CLAIM_CUSTOMER_ATTR), text(CLAIM_SOURCE_ATTR), text(CLAIM_CLOUD_ATTR))


def _first_text(attrs: Mapping[str, Any], names: Sequence[str]) -> str | None:
    for name in names:
        value = attrs.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _identifier(value: Any, limit: int) -> tuple[str | None, str | None]:
    """(clean value, None) or (None, reason)."""
    if not isinstance(value, str):
        return None, "invalid"
    text = value.strip()
    if not text:
        return None, "invalid"
    if len(text) > limit:
        return None, "too_long"
    if "://" in text or not _IDENTIFIER.fullmatch(text):
        return None, "invalid"
    return text, None


def _count_drop(drops: Counter[str] | None, attr: str, reason: str) -> None:
    if drops is not None:
        drops[f"{attr}:{reason}"] += 1  # names the attribute and reason, never the value


def _tool_identity(
    attrs: Mapping[str, Any], kind: str, drops: Counter[str] | None
) -> dict[str, str] | None:
    value = attrs.get(TOOL_NAME_ATTR)
    if kind != "tool_call" or not isinstance(value, str) or not value:
        return None
    name, reason = _identifier(value, TOOL_NAME_MAX)
    if name is None:
        _count_drop(drops, TOOL_NAME_ATTR, reason or "invalid")
        return None
    return {"tool_name": name, "external_tool_id": name}


def _service_candidate(
    attrs: Mapping[str, Any], name_attr: str, ns_attr: str | None, drops: Counter[str] | None
) -> str | None:
    raw = attrs.get(name_attr)
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if raw == "unknown_service" or raw.startswith("unknown_service:"):
        return None  # SDK default: treated as absent
    namespace = attrs.get(ns_attr) if ns_attr else None
    if isinstance(namespace, str) and namespace.strip():
        raw = f"{namespace.strip()}/{raw}"
    value, reason = _identifier(raw, SERVICE_ID_MAX)
    if value is None:
        # An invalid value is counted and the next source is tried.
        _count_drop(drops, name_attr, reason or "invalid")
    return value


def _service_identity(
    attrs: Mapping[str, Any], resource_attrs: Mapping[str, Any], drops: Counter[str] | None
) -> dict[str, str] | None:
    for name_attr, ns_attr in SPAN_SERVICE_ATTRS:
        found = _service_candidate(attrs, name_attr, ns_attr, drops)
        if found:
            return {"external_service_id": found}
    found = _service_candidate(resource_attrs, *RESOURCE_SERVICE_ATTRS, drops)
    return {"external_service_id": found} if found else None


def _valid_host(value: str) -> bool:
    if len(value) > HOST_MAX:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    return all(_HOST_LABEL.fullmatch(label) for label in value.split("."))


def _mcp_server_ref(attrs: Mapping[str, Any], drops: Counter[str] | None) -> str | None:
    if MCP_METHOD_ATTR not in attrs or attrs.get(SERVER_ADDRESS_ATTR) is None:
        return None
    value = attrs[SERVER_ADDRESS_ATTR]
    if isinstance(value, str) and _valid_host(value):
        return value
    _count_drop(drops, SERVER_ADDRESS_ATTR, "invalid")
    return None


def _as_count(value: Any) -> int | None:
    """Non-negative integer or None. Accepts JSON ints, int64 strings and integral doubles."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        number = int(value)
    else:
        return None
    return number if number >= 0 else None


def _first_count(attrs: Mapping[str, Any], names: Sequence[str]) -> int | None:
    for name in names:
        if name in attrs:
            count = _as_count(attrs[name])
            if count is not None:
                return count
    return None


def _nanos(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        return None
    return number if number > 0 else None


def format_nanos(nanos: int) -> str:
    seconds, frac = divmod(nanos, 1_000_000_000)
    stamp = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{frac:09d}Z"


def _validate(data: dict[str, Any]) -> TelemetryEvent:
    try:
        return TelemetryEvent.model_validate(data)
    except ValidationError as exc:
        raise MappingError(ReasonCode.INVALID_EVENT) from exc


def map_span(
    span: Any,
    scope: Scope,
    ingestion_time: str,
    *,
    resource: Any = None,
    drops: Counter[str] | None = None,
) -> TelemetryEvent:
    if not isinstance(span, Mapping):
        raise MappingError(ReasonCode.INVALID_EVENT)
    trace_id, span_id = span.get("traceId"), span.get("spanId")
    if not (
        isinstance(trace_id, str)
        and _HEX32.fullmatch(trace_id)
        and isinstance(span_id, str)
        and _HEX16.fullmatch(span_id)
    ):
        raise MappingError(ReasonCode.INVALID_TRACE_ID)
    start = _nanos(span.get("startTimeUnixNano"))
    if start is None:
        raise MappingError(ReasonCode.MISSING_TIME)
    end = _nanos(span.get("endTimeUnixNano"))
    attrs = attributes_to_dict(span.get("attributes"))
    status = span.get("status")
    code = status.get("code") if isinstance(status, Mapping) else None
    tokens = {
        "input": _first_count(attrs, INPUT_TOKEN_ATTRS),
        "output": _first_count(attrs, OUTPUT_TOKEN_ATTRS),
        "cached": _first_count(attrs, CACHED_TOKEN_ATTRS),
        "reasoning": _first_count(attrs, REASONING_TOKEN_ATTRS),
    }
    parent = span.get("parentSpanId")
    operation = attrs.get(OPERATION_ATTR)
    span_kind = (
        _OPERATION_KIND.get(operation, "unknown") if isinstance(operation, str) else "unknown"
    )
    resource_attrs = attributes_to_dict(
        resource.get("attributes") if isinstance(resource, Mapping) else None
    )
    identity: dict[str, Any] = {}
    tool = _tool_identity(attrs, span_kind, drops)
    if tool is not None:
        identity["tool"] = tool
    service = _service_identity(attrs, resource_attrs, drops)
    if service is not None:
        identity["service"] = service
    mcp_ref = _mcp_server_ref(attrs, drops)
    if mcp_ref is not None:
        identity["mcp_server_ref"] = mcp_ref
    return _validate(
        {
            **identity,
            "schema_version": SCHEMA_VERSION_IDENTITY if identity else SCHEMA_VERSION,
            "event_id": f"{trace_id}:{span_id}",
            "event_time": format_nanos(start),
            "ingestion_time": ingestion_time,
            "cloud": scope.cloud,
            "customer_id": scope.customer_id,
            "source_id": scope.source_id,
            "external_agent_id": _first_text(attrs, AGENT_ID_ATTRS),
            "request_id": _first_text(attrs, REQUEST_ID_ATTRS),
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent if isinstance(parent, str) and parent else None,
            "span_kind": span_kind,
            "provider": _first_text(attrs, PROVIDER_ATTRS),
            "model": _first_text(attrs, MODEL_ATTRS),
            "outcome": _STATUS_OUTCOME.get(code, "unknown"),
            "duration_ms": (end - start) // 1_000_000 if end is not None and end >= start else None,
            "token_breakdown": tokens if any(v is not None for v in tokens.values()) else None,
        }
    )


def map_metric_point(name: str, point: Any, scope: Scope, ingestion_time: str) -> TelemetryEvent:
    """One sum/gauge data point of a ``TOKEN_METRICS`` metric -> one TelemetryEvent."""
    field = TOKEN_METRICS[name]
    if not isinstance(point, Mapping):
        raise MappingError(ReasonCode.INVALID_METRIC_VALUE)
    raw_value = point["asInt"] if "asInt" in point else point.get("asDouble")
    count = _as_count(raw_value)
    if count is None:
        raise MappingError(ReasonCode.INVALID_METRIC_VALUE)
    when = _nanos(point.get("timeUnixNano"))
    if when is None:
        raise MappingError(ReasonCode.MISSING_TIME)
    attrs = attributes_to_dict(point.get("attributes"))
    digest = hashlib.sha256(
        json.dumps([name, when, sorted(attrs.items())], default=str).encode("utf-8")
    ).hexdigest()[:32]
    return _validate(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"metric:{digest}",
            "event_time": format_nanos(when),
            "ingestion_time": ingestion_time,
            "cloud": scope.cloud,
            "customer_id": scope.customer_id,
            "source_id": scope.source_id,
            "request_id": _first_text(attrs, REQUEST_ID_ATTRS),
            "provider": _first_text(attrs, PROVIDER_ATTRS),
            "model": _first_text(attrs, MODEL_ATTRS),
            "span_kind": "unknown",
            "outcome": "unknown",
            "token_breakdown": {field: count},
        }
    )


def metric_kind(metric: Mapping[str, Any]) -> str | None:
    """Which data-point container the metric uses (``sum``, ``gauge``, ``histogram``, ...)."""
    for kind in ("sum", "gauge", *UNSUPPORTED_METRIC_KINDS):
        if kind in metric:
            return kind
    return None
