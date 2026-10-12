import socket
from typing import Any, NoReturn

import pytest
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.cloud.settings import Settings
from neurosphere_core.observability import configure_telemetry, get_logger, telemetry


def _blocked(*_a: Any, **_k: Any) -> NoReturn:
    raise AssertionError("network access attempted")


def test_local_setup_and_emission_make_no_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)

    # Even an explicit connection string is ignored when NS_ENV=local.
    t = configure_telemetry(
        Settings(env="local"),
        azure_monitor_connection_string="InstrumentationKey=00000000-fake",
    )
    t.slo.record_api_request(route="/x", method="GET", status_code=500, duration_ms=1.0)
    t.slo.record_map_freshness_lag(lag_seconds=1.0, source="s")
    with t.tracer("x").start_as_current_span("op"):
        get_logger("t.egress").info("hello")
    t.meter_provider.force_flush()
    t.shutdown()


def test_no_azure_exporter_without_explicit_configuration_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry, "_azure_exporters", _blocked)
    t = configure_telemetry(Settings(env="dev", cloud=CloudName.COMMERCIAL))
    t.shutdown()
