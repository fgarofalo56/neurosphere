"""Tracer and meter provider setup. No exporters unless explicitly configured; none in local."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from neurosphere_core.cloud.settings import Settings
from neurosphere_core.observability.metrics import SloMetrics


@dataclass(frozen=True)
class Telemetry:
    """Providers are returned, never installed globally, so tests and services stay isolated."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    slo: SloMetrics

    def tracer(self, name: str) -> Tracer:
        return self.tracer_provider.get_tracer(name)

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def _azure_exporters(
    connection_string: str,
) -> tuple[PeriodicExportingMetricReader, BatchSpanProcessor]:
    # Lazy import: the Azure exporter is only loaded when explicitly configured.
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorMetricExporter,
        AzureMonitorTraceExporter,
    )

    return (
        PeriodicExportingMetricReader(
            AzureMonitorMetricExporter(connection_string=connection_string)
        ),
        BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=connection_string)),
    )


def configure_telemetry(
    settings: Settings,
    *,
    service_name: str = "neurosphere",
    azure_monitor_connection_string: str | None = None,
    metric_readers: Sequence[MetricReader] = (),
    span_processors: Sequence[SpanProcessor] = (),
) -> Telemetry:
    """Build providers.

    The Azure Monitor exporter is attached only when a connection string is passed AND NS_ENV
    is not local. metric_readers/span_processors are for tests and custom sinks.
    """
    readers = list(metric_readers)
    processors = list(span_processors)
    if azure_monitor_connection_string and settings.env != "local":
        reader, processor = _azure_exporters(azure_monitor_connection_string)
        readers.append(reader)
        processors.append(processor)

    resource = Resource.create({"service.name": service_name})
    tracer_provider = TracerProvider(resource=resource)
    for p in processors:
        tracer_provider.add_span_processor(p)
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    return Telemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        slo=SloMetrics(meter_provider.get_meter("neurosphere_core.slo")),
    )
