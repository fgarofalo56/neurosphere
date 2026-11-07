"""PRP-05 G1: the API emits ns.api.request.* and a correlated span; local makes no egress."""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from neurosphere_api import main
from neurosphere_api.app import create_app
from neurosphere_core.cloud import Settings
from neurosphere_core.observability import (
    SLO_METRIC_NAMES,
    Telemetry,
    configure_telemetry,
)
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_CID = "client-corr-1234"
_REPO = Path(__file__).resolve().parents[4]


def _points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        p
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == name
        for p in m.data.data_points
    ]


def _instrumented(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[InMemoryMetricReader, InMemorySpanExporter]:
    """Route main.create()'s real configure_telemetry call through in-memory sinks."""
    reader = InMemoryMetricReader()
    exporter = InMemorySpanExporter()

    def configure(settings: Settings, **kwargs: Any) -> Telemetry:
        return configure_telemetry(
            settings,
            metric_readers=[reader],
            span_processors=[SimpleSpanProcessor(exporter)],
            **kwargs,
        )

    monkeypatch.setattr(main, "configure_telemetry", configure)
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.delenv("NS_SCAN_ENABLED", raising=False)
    monkeypatch.delenv("NS_INGEST_PRODUCERS_FILE", raising=False)
    return reader, exporter


def test_real_create_records_slo_metrics_and_correlated_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, exporter = _instrumented(monkeypatch)
    client = TestClient(main.create(), raise_server_exceptions=False)

    ok = client.get("/healthz", headers={"x-correlation-id": _CID})
    missing = client.get("/no/such/path/12345")

    assert ok.headers["x-correlation-id"] == _CID
    assert "x-correlation-id" in missing.headers
    durations = _points(reader, "ns.api.request.duration")
    assert sum(p.count for p in durations) == 2
    routes = {p.attributes["http.route"] for p in durations}
    assert "/healthz" in routes
    assert "unmatched" in routes  # raw paths never become labels
    assert not any("12345" in str(p.attributes) for p in durations)

    spans = exporter.get_finished_spans()
    healthz = next(s for s in spans if (s.attributes or {}).get("http.route") == "/healthz")
    assert (healthz.attributes or {})["ns.correlation_id"] == _CID


def test_server_errors_count_in_error_metric_with_route_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = InMemoryMetricReader()
    telemetry = configure_telemetry(Settings(env="local"), metric_readers=[reader])
    router = APIRouter()

    @router.get("/items/{item_id}")
    def boom(item_id: str) -> None:
        raise RuntimeError(item_id)

    app: FastAPI = create_app(
        Settings(env="local"), extra_routers={"/t": router}, telemetry=telemetry
    )
    r = TestClient(app, raise_server_exceptions=False).get("/t/items/secret-id-42")

    assert r.status_code == 500
    errors = _points(reader, "ns.api.request.errors")
    assert sum(p.value for p in errors) == 1
    assert errors[0].attributes["http.route"] == "/t/items/{item_id}"
    assert "secret-id-42" not in str(errors[0].attributes)


def test_app_without_telemetry_still_works() -> None:
    r = TestClient(create_app(Settings(env="local"))).get("/healthz")
    assert r.status_code == 200
    assert "x-correlation-id" in r.headers


def _charted_metric_names() -> set[str]:
    names: set[str] = set()
    for path in sorted((_REPO / "infra" / "observability").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        json.loads(text)  # must stay valid JSON
        names.update(re.findall(r"\bns(?:\.[a-z_]+)+", text))
    return names


def test_every_charted_metric_is_emitted_by_slo_metrics() -> None:
    charted = _charted_metric_names()
    assert charted, "no ns.* metric names found in infra/observability"
    assert charted <= set(SLO_METRIC_NAMES), charted - set(SLO_METRIC_NAMES)


def _blocked(*_a: Any, **_k: Any) -> NoReturn:
    raise AssertionError("network access attempted")


def test_local_create_and_request_make_no_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    # Even an explicit connection string is ignored when NS_ENV=local.
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=00000000-fake")
    monkeypatch.delenv("NS_SCAN_ENABLED", raising=False)
    monkeypatch.delenv("NS_INGEST_PRODUCERS_FILE", raising=False)
    app = main.create()
    client = TestClient(app)
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    # Windows asyncio builds its self-pipe with a loopback socketpair, so loopback is allowed;
    # anything else (an exporter reaching a remote endpoint) fails the test.
    def _loopback_only(address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            _blocked()

    def guarded_connect(self: socket.socket, address: Any) -> None:
        _loopback_only(address)
        real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        _loopback_only(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    assert client.get("/healthz").status_code == 200
    telemetry = app.state.telemetry
    telemetry.meter_provider.force_flush()
    telemetry.shutdown()
