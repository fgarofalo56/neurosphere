# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from ...interactions.v1 import detection_finding
from . import telemetry_event


class ContentPart(BaseModel):
    """
    One part of the interaction content, exactly as the producer observed it (not yet redacted).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    part: detection_finding.ContentPartKind
    text: Annotated[
        StrictStr,
        Field(
            max_length=32768,
            min_length=1,
            pattern="^[^\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F]+$",
        ),
    ]
    """
    Part text, 1 to 32768 characters, no control characters except tab, CR and LF.
    """
    truncated: StrictBool | None = False
    """
    True when the producer cut the text before sending.
    """


class ContentEnvelope(BaseModel):
    """
    Transient opt-in content push (PRP-99): the prompt, response and tool text of one observed event, sent to the ingest edge only when a capture policy allows it. It is never stored, published, logged or returned; the edge redacts it (RedactedContent) and keeps only metadata on the event (payload_ref). The pair (source_id, event_id) joins it to its TelemetryEvent. Nothing but this schema and RedactedContent carries text; no other schema references it. Rule JSON Schema cannot express, enforced by the Python validator check_content_envelope_parts in tests/contracts/validators.py: at most one part per kind.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    cloud: Literal["commercial", "government"]
    """
    Azure cloud boundary the content belongs to. Government data is never bridged to Commercial.
    """
    source_id: telemetry_event.Identifier
    """
    Producer that emitted the event.
    """
    event_id: telemetry_event.Identifier
    """
    Source-assigned event identifier; with source_id it joins this envelope to its TelemetryEvent.
    """
    trace_id: telemetry_event.TraceId
    """
    W3C/OpenTelemetry trace ID, 32 lowercase hex characters.
    """
    span_id: telemetry_event.SpanId | None = None
    """
    Span ID, 16 lowercase hex characters. Null when not reported.
    """
    occurred_at: telemetry_event.Timestamp
    """
    When the observed event happened at the source (RFC 3339 UTC).
    """
    parts: Annotated[list[ContentPart], Field(max_length=5, min_length=1)]
    """
    Content parts, one per kind, 1 to 5.
    """
