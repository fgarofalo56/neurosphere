"""PRP-05 G1: the worker entrypoint configures telemetry; local makes no network call."""

from __future__ import annotations

import socket
from typing import Any, NoReturn

import pytest
from neurosphere_workers.runtime import __main__ as entry


def _blocked(*_a: Any, **_k: Any) -> NoReturn:
    raise AssertionError("network access attempted")


def test_build_telemetry_local_ignores_connection_string_and_makes_no_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)

    telemetry = entry.build_telemetry(
        {"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=0-fake"}
    )
    telemetry.slo.record_api_request(route="/x", method="GET", status_code=200, duration_ms=1.0)
    telemetry.meter_provider.force_flush()
    telemetry.shutdown()


@pytest.mark.asyncio
async def test_amain_configures_and_shuts_down_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    seen: list[str] = []

    class _Fake:
        def shutdown(self) -> None:
            seen.append("shutdown")

    async def fake_run_roles(*_a: Any, **_k: Any) -> int:
        seen.append("run")
        return 0

    monkeypatch.setattr(entry, "build_telemetry", lambda *_a, **_k: _Fake())
    monkeypatch.setattr(entry, "run_roles", fake_run_roles)
    monkeypatch.setattr(entry.RuntimeConfig, "from_env", classmethod(lambda cls: object()))

    assert await entry._amain(None) == 0  # pyright: ignore[reportPrivateUsage]
    assert seen == ["run", "shutdown"]
