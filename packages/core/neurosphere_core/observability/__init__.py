"""Self-observability: OTel setup, redacted JSON logging, SLO metric names."""

from neurosphere_core.observability.jsonlog import JsonFormatter, get_logger
from neurosphere_core.observability.metrics import (
    METRIC_API_REQUEST_DURATION,
    METRIC_API_REQUEST_ERRORS,
    METRIC_CATALOG_QUERY_DURATION,
    METRIC_DASHBOARD_QUERY_DURATION,
    METRIC_MAP_FRESHNESS_LAG,
    SLO_METRIC_NAMES,
    SloMetrics,
)
from neurosphere_core.observability.redaction import (
    REDACTED,
    RedactionFilter,
    redact_text,
    redact_value,
)
from neurosphere_core.observability.telemetry import Telemetry, configure_telemetry

__all__ = [
    "METRIC_API_REQUEST_DURATION",
    "METRIC_API_REQUEST_ERRORS",
    "METRIC_CATALOG_QUERY_DURATION",
    "METRIC_DASHBOARD_QUERY_DURATION",
    "METRIC_MAP_FRESHNESS_LAG",
    "REDACTED",
    "SLO_METRIC_NAMES",
    "JsonFormatter",
    "RedactionFilter",
    "SloMetrics",
    "Telemetry",
    "configure_telemetry",
    "get_logger",
    "redact_text",
    "redact_value",
]
