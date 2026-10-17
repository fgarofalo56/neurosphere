"""G03 live script: provisioning preconditions refuse before anything is created."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g03_live.py"
SUB = "00000000-1111-2222-3333-444444444444"
ENDPOINT = "https://acct1.documents.azure.com:443/"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g03_live_refuses_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Res:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


class _Runner:
    def __init__(self, active: str = SUB, rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._active = active
        self._rc = rc

    def __call__(self, args: Sequence[str]) -> _Res:
        self.calls.append(list(args))
        return _Res(self._rc, self._active + "\n")


def _env(monkeypatch: pytest.MonkeyPatch, rg: str | None, sub: str | None, ep: str = ENDPOINT):
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_G03_COSMOS_ENDPOINT", ep)
    for key, val in (("NS_G03_RESOURCE_GROUP", rg), ("NS_G03_SUBSCRIPTION", sub)):
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)


@pytest.mark.parametrize(
    ("rg", "sub", "endpoint", "needle"),
    [
        (None, SUB, ENDPOINT, "NS_G03_RESOURCE_GROUP"),
        ("rg-g03", None, ENDPOINT, "NS_G03_SUBSCRIPTION"),
        ("rg;calc", SUB, ENDPOINT, "malformed"),
        ("rg-g03", "not-a-guid", ENDPOINT, "GUID"),
        ("rg-g03", SUB, "https://-bad_name.documents.azure.com/", "account name"),
    ],
)
def test_malformed_or_missing_config_refuses_before_any_az_call(
    rg: str | None,
    sub: str | None,
    endpoint: str,
    needle: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, rg, sub, endpoint)
    runner = _Runner()
    assert _load().main([], runner=runner) == 2
    assert needle in capsys.readouterr().err
    assert runner.calls == []


def test_subscription_mismatch_refuses_with_no_create(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, "rg-g03", SUB)
    runner = _Runner(active="99999999-1111-2222-3333-444444444444")
    assert _load().main([], runner=runner) == 2
    assert "does not match" in capsys.readouterr().err
    assert runner.calls == [["account", "show", "--query", "id", "--output", "tsv"]]


def test_az_account_show_failure_refuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, "rg-g03", SUB)
    runner = _Runner(rc=1)
    assert _load().main([], runner=runner) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert len(runner.calls) == 1


def test_approval_is_checked_before_provisioning_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    monkeypatch.delenv("NS_G03_RESOURCE_GROUP", raising=False)
    runner = _Runner()
    assert _load().main([], runner=runner) == 2
    assert "NS_LIVE_APPROVED" in capsys.readouterr().err
    assert runner.calls == []
