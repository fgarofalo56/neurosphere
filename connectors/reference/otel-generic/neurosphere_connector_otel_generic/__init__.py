"""Generic OpenTelemetry push connector (PRP-09 item 3).

Pushes OTLP/JSON spans and metrics, and Pydantic-validated CloudEvents, to the PRP-07 ingest
edge with a vault-referenced producer credential. Prompt/response bodies are dropped before
send. Specs: OTLP https://opentelemetry.io/docs/specs/otlp/ and CloudEvents 1.0
https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md (observed 2026-10-17).
"""

from neurosphere_connector_otel_generic.connector import (
    CREDENTIAL_NAME,
    DEFAULT_CREDENTIAL_REF,
    OTLP_SPEC_URL,
    SPEC_OBSERVED_DATE,
    OtelGenericConnector,
    PushSummary,
)
from neurosphere_connector_otel_generic.convert import (
    CloudEventIn,
    readable_spans_to_otlp,
    redact_outgoing,
    telemetry_event_to_cloudevent,
)
from neurosphere_connector_otel_generic.exporter import ConnectorSpanExporter

__all__ = [
    "CREDENTIAL_NAME",
    "DEFAULT_CREDENTIAL_REF",
    "OTLP_SPEC_URL",
    "SPEC_OBSERVED_DATE",
    "CloudEventIn",
    "ConnectorSpanExporter",
    "OtelGenericConnector",
    "PushSummary",
    "readable_spans_to_otlp",
    "redact_outgoing",
    "telemetry_event_to_cloudevent",
]
