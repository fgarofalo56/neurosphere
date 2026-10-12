from typing import Any

from neurosphere_core.cloud.settings import Settings
from neurosphere_core.observability import SLO_METRIC_NAMES, configure_telemetry
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

EXPECTED = {
    "ns.api.request.duration",
    "ns.api.request.errors",
    "ns.dashboard.query.duration",
    "ns.catalog.query.duration",
    "ns.map.freshness.lag",
}


def test_slo_names_are_the_contract() -> None:
    assert set(SLO_METRIC_NAMES) == EXPECTED
    assert len(SLO_METRIC_NAMES) == len(EXPECTED)


def test_all_slo_metrics_emitted_via_in_memory_reader() -> None:
    reader = InMemoryMetricReader()
    t = configure_telemetry(Settings(env="local"), metric_readers=[reader])
    t.slo.record_api_request(route="/x", method="GET", status_code=200, duration_ms=12.0)
    t.slo.record_api_request(route="/x", method="GET", status_code=503, duration_ms=30.0)
    t.slo.record_dashboard_query(duration_ms=800.0, dashboard="cost")
    t.slo.record_catalog_query(duration_ms=90.0, operation="get")
    t.slo.record_map_freshness_lag(lag_seconds=4.0, source="events")
    data = reader.get_metrics_data()
    assert data is not None
    metrics: list[Any] = [
        m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    ]
    assert {m.name for m in metrics} == EXPECTED
    errors = next(m for m in metrics if m.name == "ns.api.request.errors")
    assert sum(p.value for p in errors.data.data_points) == 1
    t.shutdown()


def test_tracer_uses_in_memory_exporter() -> None:
    exporter = InMemorySpanExporter()
    t = configure_telemetry(Settings(env="local"), span_processors=[SimpleSpanProcessor(exporter)])
    with t.tracer("test").start_as_current_span("op"):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["op"]
    t.shutdown()
