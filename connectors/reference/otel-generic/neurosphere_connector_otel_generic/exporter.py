"""``SpanExporter`` adapter: plug the connector into an ``opentelemetry-sdk`` pipeline.

``BatchSpanProcessor`` calls ``export`` from its own worker thread, synchronously. The connector
is async, so the adapter runs it on one dedicated event loop thread (the HTTP client is then
only ever used from a single loop). Failures return ``FAILURE``; only the error code is logged.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Sequence

from neurosphere_core.errors import NeuroSphereError
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from neurosphere_connector_otel_generic.connector import OtelGenericConnector

__all__ = ["ConnectorSpanExporter"]

_log = logging.getLogger("neurosphere_connector_otel_generic")


class ConnectorSpanExporter(SpanExporter):
    def __init__(self, connector: OtelGenericConnector, *, timeout_seconds: float = 60.0) -> None:
        self._connector = connector
        self._timeout = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="ns-otel-exporter", daemon=True
        )
        self._thread.start()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        future = asyncio.run_coroutine_threadsafe(self._connector.export_spans(spans), self._loop)
        try:
            future.result(timeout=self._timeout)
        except NeuroSphereError as exc:
            _log.warning("span export failed", extra={"code": exc.code})
            return SpanExportResult.FAILURE
        except Exception:
            future.cancel()
            _log.warning("span export failed", extra={"code": "internal_error"})
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def shutdown(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        if not self._loop.is_closed() and not self._loop.is_running():
            self._loop.close()
