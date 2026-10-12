"""SLO metric names (defined once; dashboards in PRP-05 item 5 reference these) and recorders."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from opentelemetry.metrics import Meter

METRIC_API_REQUEST_DURATION: Final = "ns.api.request.duration"
METRIC_API_REQUEST_ERRORS: Final = "ns.api.request.errors"
METRIC_DASHBOARD_QUERY_DURATION: Final = "ns.dashboard.query.duration"
METRIC_CATALOG_QUERY_DURATION: Final = "ns.catalog.query.duration"
METRIC_MAP_FRESHNESS_LAG: Final = "ns.map.freshness.lag"

SLO_METRIC_NAMES: Final = (
    METRIC_API_REQUEST_DURATION,
    METRIC_API_REQUEST_ERRORS,
    METRIC_DASHBOARD_QUERY_DURATION,
    METRIC_CATALOG_QUERY_DURATION,
    METRIC_MAP_FRESHNESS_LAG,
)

SLO_METRIC_UNITS: Final = MappingProxyType(
    {
        METRIC_API_REQUEST_DURATION: "ms",
        METRIC_API_REQUEST_ERRORS: "{error}",
        METRIC_DASHBOARD_QUERY_DURATION: "ms",
        METRIC_CATALOG_QUERY_DURATION: "ms",
        METRIC_MAP_FRESHNESS_LAG: "s",
    }
)


class SloMetrics:
    """Instruments for the SLO metrics. Attributes must stay low-cardinality (no user ids)."""

    def __init__(self, meter: Meter) -> None:
        u = SLO_METRIC_UNITS
        self._api_duration = meter.create_histogram(
            METRIC_API_REQUEST_DURATION, unit=u[METRIC_API_REQUEST_DURATION]
        )
        self._api_errors = meter.create_counter(
            METRIC_API_REQUEST_ERRORS, unit=u[METRIC_API_REQUEST_ERRORS]
        )
        self._dashboard = meter.create_histogram(
            METRIC_DASHBOARD_QUERY_DURATION, unit=u[METRIC_DASHBOARD_QUERY_DURATION]
        )
        self._catalog = meter.create_histogram(
            METRIC_CATALOG_QUERY_DURATION, unit=u[METRIC_CATALOG_QUERY_DURATION]
        )
        self._freshness = meter.create_histogram(
            METRIC_MAP_FRESHNESS_LAG, unit=u[METRIC_MAP_FRESHNESS_LAG]
        )

    def record_api_request(
        self, *, route: str, method: str, status_code: int, duration_ms: float
    ) -> None:
        """Record duration; 5xx responses also count as errors."""
        self._api_duration.record(
            duration_ms,
            {
                "http.route": route,
                "http.request.method": method,
                "http.response.status_code": status_code,
            },
        )
        if status_code >= 500:
            self.record_api_error(route=route, method=method, error_code=str(status_code))

    def record_api_error(self, *, route: str, method: str, error_code: str) -> None:
        self._api_errors.add(
            1, {"http.route": route, "http.request.method": method, "error.type": error_code}
        )

    def record_dashboard_query(self, *, duration_ms: float, dashboard: str) -> None:
        self._dashboard.record(duration_ms, {"ns.dashboard": dashboard})

    def record_catalog_query(self, *, duration_ms: float, operation: str) -> None:
        self._catalog.record(duration_ms, {"ns.catalog.operation": operation})

    def record_map_freshness_lag(self, *, lag_seconds: float, source: str) -> None:
        self._freshness.record(lag_seconds, {"ns.map.source": source})
