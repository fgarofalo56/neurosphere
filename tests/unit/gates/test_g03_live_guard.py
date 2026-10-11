"""G03 live script guard: refuses without NS_LIVE_APPROVED=1 and touches no network."""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g03_live.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g03_live_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def net_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def boom(name: str):
        def _raise(*_a: object, **_k: object):
            calls.append(name)
            raise AssertionError(f"network touched: {name}")

        return _raise

    monkeypatch.setattr(socket, "socket", boom("socket"))
    monkeypatch.setattr(socket, "create_connection", boom("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", boom("getaddrinfo"))
    return calls


@pytest.mark.parametrize("value", [None, "0", "true", "", "yes"])
def test_refuses_without_approval_and_no_network(
    value: str | None,
    net_calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if value is None:
        monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    else:
        monkeypatch.setenv("NS_LIVE_APPROVED", value)
    monkeypatch.setenv("NS_G03_COSMOS_ENDPOINT", "https://example.invalid:443/")
    before = {m for m in sys.modules if m.startswith("azure")}
    rc = _load().main([])
    assert rc != 0
    assert "NS_LIVE_APPROVED" in capsys.readouterr().err
    assert net_calls == []
    assert {m for m in sys.modules if m.startswith("azure")} == before


@pytest.mark.parametrize("endpoint", [None, "", "http://localhost:8081"])
def test_approved_but_bad_endpoint_fails_without_network(
    endpoint: str | None,
    net_calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    if endpoint is None:
        monkeypatch.delenv("NS_G03_COSMOS_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("NS_G03_COSMOS_ENDPOINT", endpoint)
    rc = _load().main([])
    assert rc != 0
    assert "NS_G03_COSMOS_ENDPOINT" in capsys.readouterr().err
    assert net_calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://acct.documents.azure.us:443/",
        "https://acct.documents.azure.us/",
        "https://acct.gremlin.cosmos.usgovcloudapi.net:443/",
        "https://example.azure.us/",
    ],
)
def test_approved_government_endpoint_is_rejected_without_network(
    endpoint: str,
    net_calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_G03_COSMOS_ENDPOINT", endpoint)
    before = {m for m in sys.modules if m.startswith("azure")}
    rc = _load().main([])
    assert rc != 0
    assert "Government" in capsys.readouterr().err
    assert net_calls == []
    assert {m for m in sys.modules if m.startswith("azure")} == before


def test_no_secret_bearing_cli_option() -> None:
    parser = _load().build_parser()
    flags = [f for a in parser._actions for f in a.option_strings]  # pyright: ignore[reportPrivateUsage]
    assert flags
    banned = ("key", "secret", "connection", "token", "password")
    for flag in flags:
        assert not any(w in flag.lower() for w in banned)


def test_subprocess_refuses_end_to_end() -> None:
    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr
