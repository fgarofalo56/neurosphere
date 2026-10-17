"""Pure conversions to the exact wire formats the PRP-07 ingest edge accepts.

The edge owns the OTLP -> TelemetryEvent mapping (``neurosphere_api.ingest.otlp_mapping``), so
this connector sends OTLP/JSON for spans and metrics and does not map to TelemetryEvent itself:
there is one mapping, at the edge. Structured TelemetryEvent data travels as a CloudEvent of
type ``com.neurosphere.telemetry.v1``.

Rules that hold everywhere in this module:

* Unknown stays unknown. A span without an end time has no ``endTimeUnixNano``; an attribute
  that is missing is omitted. Nothing is defaulted to 0, "" or a made-up id.
* Prompt/response bodies are removed (``drop_body_fields``) before anything leaves the process.
* Trace, span and parent-span ids are preserved verbatim (lowercase hex).

CloudEvents are validated with the Pydantic model below; the ``cloudevents`` SDK is not allowed
by the licence gate. Specs: OTLP https://opentelemetry.io/docs/specs/otlp/ and CloudEvents 1.0
https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md (both observed 2026-10-17).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, Literal

from neurosphere_core.payload import CLOUDEVENT_TYPE_TELEMETRY, drop_body_fields, find_body_fields
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

__all__ = [
    "CloudEventIn",
    "attribute",
    "readable_spans_to_otlp",
    "redact_outgoing",
    "telemetry_event_to_cloudevent",
]

# Resource attributes the edge reads as producer claims (checked against the registration).
CLAIM_CUSTOMER_ATTR: Final = "neurosphere.customer_id"
CLAIM_SOURCE_ATTR: Final = "neurosphere.source_id"
CLAIM_CLOUD_ATTR: Final = "neurosphere.cloud"

_STATUS_NAME: Final = {0: "STATUS_CODE_UNSET", 1: "STATUS_CODE_OK", 2: "STATUS_CODE_ERROR"}


class CloudEventIn(BaseModel):
    """CloudEvents 1.0 context attributes the edge requires; extensions are kept."""

    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)

    specversion: Literal["1.0"]
    id: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=1024)
    type: str = Field(min_length=1, max_length=256)
    time: str | None = None
    datacontenttype: str | None = None
    data: dict[str, Any] | None = None


def redact_outgoing(document: Any) -> tuple[Any, dict[str, int]]:
    """Drop prompt/response bodies; returns the clean copy and per-name drop counts.

    Called on every outgoing document. The post-condition is checked so a regression in the
    guard fails here rather than on the wire.
    """
    # JSON round trip: the guard walks dict/list only, so tuples and other containers must be
    # normalized first or their bodies would pass through untouched.
    clean, counts = drop_body_fields(json.loads(json.dumps(document)))
    if find_body_fields(clean):  # pragma: no cover - defensive
        raise ValueError("body fields survived redaction")
    return clean, counts


def attribute(key: str, value: Any) -> dict[str, Any] | None:
    """One OTLP/JSON attribute, or None for a value the edge cannot read (non-scalar, None)."""
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}  # int64 is a string in OTLP/JSON
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    return None


def _attributes(items: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, value in (items or {}).items():
        converted = attribute(str(key), value)
        if converted is not None:
            out.append(converted)
    return out


def readable_spans_to_otlp(
    spans: Iterable[Any],
    *,
    customer_id: str | None = None,
    source_id: str | None = None,
    cloud: str | None = None,
) -> dict[str, Any]:
    """``opentelemetry-sdk`` ``ReadableSpan`` objects -> an OTLP/JSON ``ExportTraceServiceRequest``.

    Spans are grouped by resource. ``customer_id``/``source_id``/``cloud`` are optional producer
    claims; when omitted the edge fills them from the producer registration.
    """
    claims = {
        CLAIM_CUSTOMER_ATTR: customer_id,
        CLAIM_SOURCE_ATTR: source_id,
        CLAIM_CLOUD_ATTR: cloud,
    }
    groups: dict[tuple[tuple[str, str], ...], tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for span in spans:
        context = span.get_span_context()
        resource_attrs = dict(span.resource.attributes) if span.resource is not None else {}
        resource_attrs.update({k: v for k, v in claims.items() if v is not None})
        key = tuple(sorted((str(k), repr(v)) for k, v in resource_attrs.items()))
        if key not in groups:
            groups[key] = (resource_attrs, [])
        otlp: dict[str, Any] = {
            "traceId": format(context.trace_id, "032x"),
            "spanId": format(context.span_id, "016x"),
            "name": span.name,
            "attributes": _attributes(span.attributes),
        }
        if span.parent is not None:
            otlp["parentSpanId"] = format(span.parent.span_id, "016x")
        if span.start_time is not None:
            otlp["startTimeUnixNano"] = str(span.start_time)
        if span.end_time is not None:
            otlp["endTimeUnixNano"] = str(span.end_time)
        status_code = getattr(span.status.status_code, "value", None)
        if status_code in _STATUS_NAME:
            otlp["status"] = {"code": _STATUS_NAME[status_code]}
        groups[key][1].append(otlp)
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes(resource_attrs)},
                "scopeSpans": [{"spans": group}],
            }
            for resource_attrs, group in groups.values()
        ]
    }


def telemetry_event_to_cloudevent(
    event: Mapping[str, Any], *, source: str = "urn:neurosphere:connector:otel-generic"
) -> dict[str, Any]:
    """Wrap one TelemetryEvent-shaped mapping as a CloudEvent the edge accepts.

    Null/absent fields are carried exactly as given (no defaults). The event id becomes the
    CloudEvents id so replays dedupe.
    """
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("telemetry event has no event_id")
    out: dict[str, Any] = {
        "specversion": "1.0",
        "id": event_id,
        "source": source,
        "type": CLOUDEVENT_TYPE_TELEMETRY,
        "datacontenttype": "application/json",
        "data": dict(event),
    }
    when = event.get("event_time")
    if isinstance(when, str):
        out["time"] = when
    return out


def validate_cloudevents(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate each event with ``CloudEventIn``; raises ``ValueError`` (value-free message)."""
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        try:
            model = CloudEventIn.model_validate(event)
        except PydanticValidationError:
            raise ValueError(f"event {index} is not a valid CloudEvent 1.0 envelope") from None
        out.append(model.model_dump(mode="json", exclude_unset=True))
    return out
