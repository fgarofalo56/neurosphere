"""Map APIM gateway and MCP log rows (``SourceKind.APIM_GATEWAY`` / ``APIM_MCP``) to contracts.

One joined gateway row (``ApiManagementGatewayLogs`` left-joined to ``ApiManagementGatewayLlmLog``
on ``CorrelationId``) becomes exactly one ``TelemetryEvent`` plus one cost observation.

Rules:
- The request id is ``CorrelationId``. It is also the cost ``dedupe_key``, the key the ledger folds
  gateway, application and billing views of one call on.
- Gateway rows are unpriced. The amount is ``None`` (never 0, never computed here).
  ``neurosphere_contracts`` ``CostRecord.amount`` is a required decimal string, so the cost side is
  the connector-local ``GatewayCostObservation``, which mirrors the ``CostRecord`` field names and
  carries ``amount=None``; see README "Unpriced gateway cost".
- ``ApimSubscriptionId`` is sha256-hashed (hex); the raw value never leaves this module.
- Rows without an LLM side (non-LLM APIs, or ``GatewayLlmLogs`` not enabled) still map, with the
  token fields null.
- Only allowlisted columns are read; unknown columns on a row (for example the ``source_kind`` and
  ``source_id`` keys the poller adds) are ignored.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from neurosphere_contracts.telemetry.v1.telemetry_event import (
    Identifier,
    Label,
    TelemetryEvent,
    Timestamp,
    TokenBreakdown,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

__all__ = [
    "GatewayCostObservation",
    "GatewayObservation",
    "McpToolObservation",
    "hash_subscription_id",
    "map_gateway_row",
    "map_mcp_row",
]

_SCHEMA_VERSION = "1.0.0"
_PROVIDER = "azure_api_management"


class GatewayCostObservation(BaseModel):
    """Unpriced gateway-side cost observation; field names mirror ``CostRecord``."""

    model_config = ConfigDict(extra="forbid")

    cost_id: StrictStr
    dedupe_key: StrictStr  # = CorrelationId
    observation_source: Literal["gateway"] = "gateway"
    kind: Literal["estimated"] = "estimated"
    amount: None = None
    currency: None = None
    price_version: None = None
    cloud: Literal["commercial", "government"]
    customer_id: StrictStr
    domain_id: StrictStr | None = None
    source_id: StrictStr
    provider: StrictStr = _PROVIDER
    model: StrictStr | None = None
    usage_end: StrictStr
    event_ids: list[StrictStr]
    token_breakdown: TokenBreakdown | None = None
    total_tokens: Annotated[StrictInt | None, Field(ge=0)] = None
    deployment_name: StrictStr | None = None
    api_id: StrictStr | None = None
    api_revision: StrictStr | None = None
    operation_id: StrictStr | None = None
    product_id: StrictStr | None = None
    backend_id: StrictStr | None = None
    subscription_id_hash: StrictStr | None = None
    response_code: StrictInt | None = None
    backend_response_code: StrictInt | None = None
    region: StrictStr | None = None
    resource_id: StrictStr | None = None
    total_time_ms: Annotated[StrictInt | None, Field(ge=0)] = None
    backend_time_ms: Annotated[StrictInt | None, Field(ge=0)] = None
    is_stream_completion: bool | None = None


class GatewayObservation(BaseModel):
    """One ``TelemetryEvent`` plus one cost observation for one ``CorrelationId``."""

    model_config = ConfigDict(extra="forbid")

    telemetry: TelemetryEvent
    cost: GatewayCostObservation


class McpToolObservation(BaseModel):
    """One MCP gateway log row: a ``TelemetryEvent`` plus the tool name and transport."""

    model_config = ConfigDict(extra="forbid")

    telemetry: TelemetryEvent
    tool_name: StrictStr | None
    tool_count: Annotated[StrictInt | None, Field(ge=0)] = None
    transport_type: StrictStr | None = None
    resource_id: StrictStr | None = None


def hash_subscription_id(value: str) -> str:
    """sha256 hex of an APIM subscription id."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number < 0 or number != int(number):
        return None
    return int(number)


def _duration_ms(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number < 0:
        return None
    return round(number)


def _bool(row: Mapping[str, Any], name: str) -> bool | None:
    value = row.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _timestamp(row: Mapping[str, Any]) -> str:
    raw = row.get("TimeGenerated")
    if not isinstance(raw, str):
        raise ValueError("row has no TimeGenerated")
    # Log Analytics emits 7 fractional digits; fromisoformat (3.11+) truncates to microseconds.
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _correlation_id(row: Mapping[str, Any]) -> str:
    cid = _text(row, "CorrelationId")
    if cid is None:
        raise ValueError("row has no CorrelationId")
    return cid


def map_gateway_row(
    row: Mapping[str, Any],
    *,
    cloud: Literal["commercial", "government"],
    customer_id: str,
    source_id: str,
    domain_id: str | None = None,
) -> GatewayObservation:
    """Map one joined APIM_GATEWAY row; ``ValueError`` without CorrelationId or TimeGenerated."""
    cid = _correlation_id(row)
    when = _timestamp(row)
    model = _text(row, "ModelName")
    prompt = _int(row, "PromptTokens")
    completion = _int(row, "CompletionTokens")
    total = _int(row, "TotalTokens")
    has_tokens = prompt is not None or completion is not None
    success = _bool(row, "IsRequestSuccess")
    outcome: Literal["success", "error", "unknown"] = (
        "unknown" if success is None else ("success" if success else "error")
    )
    total_ms = _duration_ms(row, "TotalTime")
    subscription = _text(row, "ApimSubscriptionId")
    breakdown = TokenBreakdown(input=prompt, output=completion) if has_tokens else None

    telemetry = TelemetryEvent(
        schema_version=_SCHEMA_VERSION,
        event_id=Identifier(cid),
        event_time=Timestamp(when),
        cloud=cloud,
        customer_id=Identifier(customer_id),
        domain_id=Identifier(domain_id) if domain_id else None,
        source_id=Identifier(source_id),
        request_id=Identifier(cid),
        span_kind="model_call" if model is not None else "request",
        provider=Label(_PROVIDER) if model is not None else None,
        model=Label(model) if model is not None else None,
        outcome=outcome,
        duration_ms=total_ms,
        token_breakdown=breakdown,
    )
    cost = GatewayCostObservation(
        cost_id=f"{cid}:gateway",
        dedupe_key=cid,
        cloud=cloud,
        customer_id=customer_id,
        domain_id=domain_id,
        source_id=source_id,
        model=model,
        usage_end=when,
        event_ids=[cid],
        token_breakdown=breakdown,
        total_tokens=total,
        deployment_name=_text(row, "DeploymentName"),
        api_id=_text(row, "ApiId"),
        api_revision=_text(row, "ApiRevision"),
        operation_id=_text(row, "OperationId"),
        product_id=_text(row, "ProductId"),
        backend_id=_text(row, "BackendId"),
        subscription_id_hash=hash_subscription_id(subscription) if subscription else None,
        response_code=_int(row, "ResponseCode"),
        backend_response_code=_int(row, "BackendResponseCode"),
        region=_text(row, "Region"),
        resource_id=_text(row, "_ResourceId"),
        total_time_ms=total_ms,
        backend_time_ms=_duration_ms(row, "BackendTime"),
        is_stream_completion=_bool(row, "IsStreamCompletion"),
    )
    return GatewayObservation(telemetry=telemetry, cost=cost)


def map_mcp_row(
    row: Mapping[str, Any],
    *,
    cloud: Literal["commercial", "government"],
    customer_id: str,
    source_id: str,
    domain_id: str | None = None,
) -> McpToolObservation:
    """Map one APIM_MCP row to a ``tool_call`` ``TelemetryEvent`` plus tool name and transport."""
    cid = _correlation_id(row)
    telemetry = TelemetryEvent(
        schema_version=_SCHEMA_VERSION,
        event_id=Identifier(f"{cid}:mcp"),  # distinct from the gateway event of the same call
        event_time=Timestamp(_timestamp(row)),
        cloud=cloud,
        customer_id=Identifier(customer_id),
        domain_id=Identifier(domain_id) if domain_id else None,
        source_id=Identifier(source_id),
        request_id=Identifier(cid),
        span_kind="tool_call",
    )
    return McpToolObservation(
        telemetry=telemetry,
        tool_name=_text(row, "ToolName"),
        tool_count=_int(row, "ToolCount"),
        transport_type=_text(row, "TransportType"),
        resource_id=_text(row, "_ResourceId"),
    )
