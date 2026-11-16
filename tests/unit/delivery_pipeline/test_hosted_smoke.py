"""PRP-63 item 1: scripts/gates/hosted_smoke.py against a fake transport and a fake `az`."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import httpx
import pytest

GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
SUB = "33333333-3333-4333-8333-333333333333"
FRONTEND_HOST = "nsdemo-ui.azurewebsites.net"
API_HOST = "nsdemo-api.azurewebsites.net"
TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
SECRET_BODY = "SECRET-BODY-TEXT-eyJhbGciOi"
SECRET_HEADER = "Bearer SECRET-HEADER-VALUE"


def _load() -> ModuleType:
    sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location(
        "hosted_smoke_under_test", GATES / "hosted_smoke.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hs = _load()
sm = hs.sm

OUTPUTS = {
    "frontendHostName": {"type": "String", "value": FRONTEND_HOST},
    "apiHostName": {"type": "String", "value": API_HOST},
    "frontendSiteName": {"value": "nsdemo-ui"},
    "apiSiteName": {"value": "nsdemo-api"},
    "workersSiteName": {"value": "nsdemo-workers"},
}


class FakeAz:
    def __init__(self, outputs: object = OUTPUTS, state: str = "Running") -> None:
        self.outputs = outputs
        self.state = state
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> object:
        self.calls.append(list(args))
        if args[:3] == ["deployment", "group", "show"]:
            return sm.AzResult(0, json.dumps(self.outputs), "")
        if args[:2] == ["webapp", "show"]:
            return sm.AzResult(0, json.dumps({"state": self.state, "id": "x"}), "")
        if args[:2] == ["webapp", "restart"]:
            return sm.AzResult(0, "", "")
        body = {"value": [{"timeseries": [{"data": [{"average": 100.0}]}]}]}
        return sm.AzResult(0, json.dumps(body), "")


class Edge:
    def __init__(self, root: int = 200, fail_first: int = 0) -> None:
        self.root = root
        self.fail_first = fail_first
        self.root_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == API_HOST:
            return httpx.Response(403, text=SECRET_BODY)
        if path == "/":
            self.root_calls += 1
            if self.root_calls <= self.fail_first:
                return httpx.Response(503, text=SECRET_BODY, headers={"X-Token": SECRET_HEADER})
            return httpx.Response(self.root, text=SECRET_BODY)
        if path == "/config.json":
            cfg = {
                "cloud": "commercial",
                "tenantId": TENANT,
                "clientId": CLIENT,
                "apiBaseUrl": "/",
                "apiScope": f"api://{CLIENT}/access_as_user",
            }
            return httpx.Response(200, json=cfg, headers={"Cache-Control": "no-store"})
        if path == "/api/v1/me/domains":
            return httpx.Response(401, text=SECRET_BODY)
        return httpx.Response(404, text=SECRET_BODY)


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return ["--subscription", SUB, "--result-json", str(tmp_path / "r.json"), *extra]


def _run(tmp_path: Path, edge: Edge, az: FakeAz | None = None, *extra: str, env=None):
    sleeps: list[float] = []
    code = hs.main(
        _argv(tmp_path, *extra),
        az=az or FakeAz(),
        transport=httpx.MockTransport(edge.handler),
        sleep=sleeps.append,
        env=env if env is not None else {},
    )
    return code, sleeps


def test_all_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, sleeps = _run(tmp_path, Edge())
    assert code == 0
    assert sleeps == []
    body = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert body["ok"] is True and body["attempts"] == 1
    assert {c["name"] for c in body["checks"]} >= {"api-unauthenticated-401", "readyz-not-proxied"}
    assert "PASS" in capsys.readouterr().out


def test_one_red_check_fails_after_every_attempt(tmp_path: Path) -> None:
    code, sleeps = _run(tmp_path, Edge(root=500), None, "--attempts", "3")
    assert code == 1
    assert len(sleeps) == 2
    body = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert body["ok"] is False and body["attempts"] == 3
    assert [c["name"] for c in body["checks"] if not c["passed"]]


def test_warm_up_retry_then_green(tmp_path: Path) -> None:
    edge = Edge(fail_first=2)
    code, sleeps = _run(tmp_path, edge, None, "--attempts", "5", "--backoff-seconds", "10")
    assert code == 0
    assert sleeps == [10.0, 20.0]
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["attempts"] == 3


def test_attempts_are_bounded(tmp_path: Path) -> None:
    code, sleeps = _run(tmp_path, Edge(root=500), None, "--attempts", "999")
    assert code == 1
    assert len(sleeps) == hs.MAX_ATTEMPTS - 1


def test_no_body_or_header_value_reaches_any_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    code, _ = _run(
        tmp_path,
        Edge(fail_first=99),
        None,
        "--attempts",
        "2",
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert code == 1
    seen = capsys.readouterr()
    everything = (
        seen.out
        + seen.err
        + summary.read_text(encoding="utf-8")
        + (tmp_path / "r.json").read_text(encoding="utf-8")
    )
    assert SECRET_BODY not in everything
    assert SECRET_HEADER not in everything
    assert "| check | result | detail |" in everything


def test_restart_flag_restarts_frontend_only(tmp_path: Path) -> None:
    az = FakeAz()
    code, _ = _run(tmp_path, Edge(), az, "--restart-frontend")
    assert code == 0
    restarts = [c for c in az.calls if c[:2] == ["webapp", "restart"]]
    assert len(restarts) == 1 and "nsdemo-ui" in restarts[0]


def test_refuses_missing_outputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = _run(tmp_path, Edge(), FakeAz(outputs={}))
    assert code == 2
    assert "REFUSED" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_refuses_bad_subscription(tmp_path: Path) -> None:
    code = hs.main(
        ["--subscription", "not-a-guid", "--result-json", str(tmp_path / "r.json")], az=FakeAz()
    )
    assert code == 2


def test_refuses_without_az(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs.shutil, "which", lambda _name: None)
    assert hs.main(_argv(tmp_path)) == 2
