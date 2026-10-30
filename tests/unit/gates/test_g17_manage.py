"""G17 APIM manage gate: refusal, tokenisation, step order, inventory diff, teardown, OPEN.

Every test uses fakes for `az`, the NeuroSphere API, ARM reads and the MCP call: no subprocess,
no network. NS_LIVE_APPROVED=1 is only ever set together with those fakes.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g17_apim_manage_live.py"
SUB = "11111111-2222-3333-4444-555555555555"
FAKE_TOKEN = "eyJfake.entra.token0123456789"
FAKE_KEY = "k3y0123456789abcdef0123456789abcdef"
ENDPOINT = "https://example.openai.azure.com"
ARGS = [
    "--subscription",
    SUB,
    "--foundry-endpoint",
    ENDPOINT,
    "--foundry-deployment",
    "gpt",
    "--domain",
    "dom1",
    "--grant-entity-id",
    "commercial:c1:cat:grant:g1",
    "--mcp-entity-id",
    "commercial:c1:cat:mcp_server:m1",
    "--mcp-backend-url",
    "https://echo.example.net",
    "--mcp-audience",
    "api://g17-mcp",
    "--api-url",
    "https://ns.example.net",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g17_manage_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g17_manage_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


g17 = _load()
obs = g17.obs


class FakeAz:
    def __init__(self, resources: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.resources = resources if resources is not None else []

    def __call__(self, args: Sequence[str]) -> Any:
        a = list(args)
        self.calls.append(a)
        out: Any = ""
        if a[:2] == ["cloud", "show"]:
            out = "AzureCloud"
        elif a[:2] == ["resource", "list"]:
            out = json.dumps(self.resources)
        elif a[:2] == ["account", "get-access-token"]:
            out = FAKE_TOKEN
        elif a[:3] == ["monitor", "log-analytics", "workspace"] and a[3] == "create":
            out = json.dumps({"id": f"/subscriptions/{SUB}/rg/law", "customerId": "cid"})
        elif a[0] == "rest":
            url = a[a.index("--url") + 1]
            if "listSecrets" in url:
                out = json.dumps({"primaryKey": FAKE_KEY})
            elif a[a.index("--method") + 1] == "GET":
                out = json.dumps(
                    {
                        "properties": {
                            "provisioningState": "Succeeded",
                            "gatewayUrl": "https://x.azure-api.net",
                        },
                        "identity": {"principalId": "pid"},
                    }
                )
        elif a[:3] == ["cognitiveservices", "account", "list"]:
            out = json.dumps(
                [{"id": f"/subscriptions/{SUB}/f", "properties": {"endpoint": ENDPOINT + "/"}}]
            )
        elif a[:3] == ["role", "assignment", "list"]:
            out = "[]"
        elif a[:3] == ["role", "assignment", "create"]:
            out = json.dumps({"id": f"/subscriptions/{SUB}/ra1"})
        return obs.AzResult(0, out, "")


class FakeApi:
    """Intents succeed on the first poll; the inventory is whatever `inventories` yields."""

    def __init__(self, inventories: list[dict[str, Any]] | None = None) -> None:
        self.log: list[tuple[str, str]] = []
        self.inventories = inventories or [{"apis": [{"id": "a1"}], "backends": [{"id": "b1"}]}]
        self.mode = "observe"
        self._n = 0
        self._inv_calls = 0

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None, *, actor: str = "maker"
    ) -> dict[str, Any]:
        self.log.append((method, path))
        if path.endswith("/gateways") and method == "POST":
            return {"id": "gw-1", "customer_id": "c1", "mode": "observe"}
        if path.endswith("/inventory"):
            i = min(self._inv_calls, len(self.inventories) - 1)
            self._inv_calls += 1
            return self.inventories[i]
        if path.endswith("/mode"):
            self.mode = "manage"
            return self._view("mode")
        if re.search(r"/gateways/gw-1$", path):
            return {"mode": self.mode, "preflight": {"ok": True}}
        if path.endswith("/sync"):
            return {}
        if "/intents/" in path and method == "GET":
            return {
                "intent": {"intent_id": "i", "state": "succeeded", "action_kind": "k"},
                "execution": {"canary": {"verify_only": False}, "verify_matched": True},
            }
        if path.endswith("/intents") or "/publish" in path or "/unpublish" in path:
            return self._view("x")
        # validate / confirmation / confirm / decisions
        if path.endswith("/confirmation"):
            return self._view("x", state="awaiting_confirmation")
        return self._view("x", state="validated" if path.endswith("/validate") else "executing")

    def _view(self, tag: str, state: str = "drafted") -> dict[str, Any]:
        self._n += 1
        view = {
            "intent_id": f"i{self._n}",
            "state": state,
            "confirmation_hash": "sha256:" + "0" * 64,
        }
        return {"intent": view, "stage": "deny", "action": {"intent": view}}


class FakeArm:
    def get(self, path: str, api: str) -> tuple[dict[str, Any], str]:
        return {"properties": {"type": "Pool"}}, '"etag1"'


def _mcp_ok(_u: str, _h: Mapping[str, str], _b: dict[str, Any]) -> Any:
    return 200, {"result": {"headers": {"Host": "echo", "X-Forwarded-For": "1.2.3.4"}}}


def _gate(
    az: FakeAz | None = None,
    api: FakeApi | None = None,
    *,
    approve_all: bool = True,
    approve: set[str] | None = None,
    **kw: Any,
) -> Any:
    g = g17.ManageGate(
        run_az=az or FakeAz(),
        subscription=SUB,
        location="centralus",
        resource_group="ns-g17m-t",
        foundry_endpoint=ENDPOINT,
        foundry_deployment="gpt",
        domain="dom1",
        grant_entity_id="commercial:c1:cat:grant:g1",
        mcp_entity_id="commercial:c1:cat:mcp_server:m1",
        mcp_backend_url="https://echo.example.net",
        mcp_audience="api://g17-mcp",
        approve_all=approve_all,
        approve_steps=approve or set(),
        **kw,
    )
    g.api = api or FakeApi()
    g.arm_reader = FakeArm()
    g.mcp_caller = _mcp_ok
    g.fragment_id_for = lambda e: "frag-" + e[-2:]
    g.sleep = lambda _s: None
    return g


# ------------------------------------------------------------------ refusal


@pytest.fixture
def no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    import httpx

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a subprocess or network call was attempted")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(httpx, "request", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr("shutil.which", boom)


def test_refuses_without_approval(
    monkeypatch: pytest.MonkeyPatch, no_side_effects: None, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    az, api = FakeAz(), FakeApi()
    assert g17.main(ARGS, runner=az, api=api) == 2
    assert az.calls == []
    assert api.log == []
    assert "NS_LIVE_APPROVED=1" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "2", " 1", "1 ", "TRUE"])
def test_refuses_other_values(
    monkeypatch: pytest.MonkeyPatch, no_side_effects: None, value: str
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", value)
    az, api = FakeAz(), FakeApi()
    assert g17.main(ARGS, runner=az, api=api) == 2
    assert az.calls == [] and api.log == []


def test_refusal_precedes_argument_parsing(
    monkeypatch: pytest.MonkeyPatch, no_side_effects: None
) -> None:
    monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    assert g17.main([]) == 2  # no required args, still a clean refusal (not an argparse exit)


def test_refuses_government_and_missing_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    az = FakeAz()
    assert g17.main([*ARGS, "--location", "usgovvirginia"], runner=az, api=FakeApi()) == 2
    assert g17.main(["--subscription", SUB], runner=az, api=FakeApi()) == 2
    assert az.calls == []


# ------------------------------------------------------------------ tokenisation


def test_evidence_tokenises_subscription_and_hides_tokens(tmp_path: Path) -> None:
    g = _gate(keep=True)
    code, ev = g17.run_gate(g)
    assert code == 0 and ev["result"] == "PASS"
    ev["tenant_note"] = f"tenant token {FAKE_TOKEN}"
    md = g17.write_evidence(
        ev, tmp_path, secrets=[FAKE_TOKEN, FAKE_KEY], hosts=["echo.example.net"]
    )
    assert md.name.startswith("manage-")
    blob = md.read_text(encoding="utf-8") + md.with_suffix(".json").read_text(encoding="utf-8")
    for needle in (SUB, FAKE_TOKEN, FAKE_KEY, "echo.example.net"):
        assert needle not in blob
    assert obs.subscription_token(SUB) in blob
    assert json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))["tokens"] == (
        g17.TOKEN_REDACTED
    )


# ------------------------------------------------------------------ ordering


def test_step_ordering_and_executor_path() -> None:
    api = FakeApi()
    g = _gate(api=api)
    code, ev = g17.run_gate(g)
    assert code == 0 and ev["result"] == "PASS"
    runs = [e.split(":", 1)[1] for e in g.events if e.startswith("run:")]
    assert runs == list(g17.STEPS)
    assert g.events[-1] == "teardown"
    names = [p["phase"] for p in ev["phases"]]
    assert names[: len(g17.STEPS)] == list(g17.STEPS)
    # Every gateway change went through drafted intents driven to completion.
    paths = [p for _m, p in api.log]
    assert any(p.endswith("/mode") for p in paths)
    assert sum(p.endswith("/confirm") for p in paths) >= 8
    kinds = {i["step"] for i in ev["intents"]}
    assert {"mode-manage", "grant-publish", "backend-swap", "cap-change", "mcp-publish"} <= kinds
    # MCP is unpublished in two intents, deny then remove.
    assert {"mcp-unpublish-1", "mcp-unpublish-2", "grant-unpublish"} <= kinds
    assert ev["credential_check"]["leaked"] == []


def test_idempotency_keys_are_stable_and_valid() -> None:
    k1 = g17.idempotency_key("grant-publish", "abc12345")
    assert k1 == g17.idempotency_key("grant-publish", "abc12345")
    assert re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", k1)
    assert g17.idempotency_key("mcp-unpublish-1", "x") != g17.idempotency_key(
        "mcp-unpublish-2", "x"
    )


# ------------------------------------------------------------------ inventory diff


def test_inventory_signature_and_diff() -> None:
    a = g17.inventory_signature({"apis": [{"id": "a1"}, {"name": "a2"}], "backends": []})
    b = g17.inventory_signature({"apis": [{"id": "a2x"}, {"id": "a1"}], "backends": []})
    d = g17.diff_signatures(a, b)
    assert d == {"apis": {"added": ["a2x"], "removed": ["a2"]}}
    assert g17.diff_signatures(a, a) == {}
    ignored = g17.inventory_signature({"apis": [{"id": "a1"}], "taken_at": "now"})
    assert "taken_at" not in ignored


def test_run_fails_when_inventory_differs_and_still_tears_down() -> None:
    inv0 = {"apis": [{"id": "a1"}]}
    inv1 = {"apis": [{"id": "a1"}, {"id": "left-behind"}]}
    az = FakeAz()
    g = _gate(az, api=FakeApi([inv0, inv1]))
    code, ev = g17.run_gate(g)
    assert code == 1 and ev["result"] == "FAIL"
    assert ev["inventory_diff"] == {"apis": {"added": ["left-behind"], "removed": []}}
    assert g.events[-1] == "teardown"
    assert any(c[:2] == ["group", "delete"] for c in az.calls)


# ------------------------------------------------------------------ credentials stripped


def test_find_headers_and_leak_detection() -> None:
    echo = g17.find_headers({"a": [{"result": {"headers": {"Authorization": "x", "Host": "h"}}}]})
    assert echo == {"authorization": "x", "host": "h"}
    assert g17.leaked_headers(echo) == ["authorization"]
    assert g17.find_headers({"nope": 1}) is None


def test_leaked_credentials_fail_the_gate_and_teardown_runs() -> None:
    g = _gate()
    g.mcp_caller = lambda _u, _h, _b: (200, {"result": {"headers": {"Authorization": "Bearer x"}}})
    code, ev = g17.run_gate(g)
    assert code == 1 and ev["result"] == "FAIL"
    assert ev["credential_check"]["leaked"] == ["authorization"]
    assert [p["status"] for p in ev["phases"] if p["phase"] == "unpublish"] == ["skipped_blocked"]
    assert g.events[-1] == "teardown"


# ------------------------------------------------------------------ teardown / OPEN


def test_teardown_attempted_when_a_step_fails() -> None:
    api = FakeApi()

    def bad(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise obs.GateError("api down")

    api.call = bad  # type: ignore[method-assign]
    az = FakeAz()
    g = _gate(az, api=api)
    code, ev = g17.run_gate(g)
    assert code == 1
    assert g.events[-1] == "teardown"
    assert any(c[:2] == ["group", "delete"] for c in az.calls)
    assert ev["result"] == "FAIL"


def test_teardown_refuses_untagged_resources_and_reports_orphans() -> None:
    az = FakeAz(resources=[{"id": "/subscriptions/x/foreign", "tags": {}}])
    g = _gate(az)
    code, ev = g17.run_gate(g)
    assert code == 3
    assert ev["orphans"]
    assert not any(c[:2] == ["group", "delete"] for c in az.calls)


def test_unapproved_step_is_open_and_blocks_later_steps() -> None:
    az = FakeAz()
    g = _gate(az, approve_all=False, approve={"provision", "diagnostics"})
    code, ev = g17.run_gate(g)
    assert code == 2 and ev["result"] == "OPEN"
    status = {p["phase"]: p["status"] for p in ev["phases"]}
    assert status["provision"] == "pass"
    assert status["import-api"] == "skipped_awaiting_operator"
    assert status["register"] == "skipped_blocked"
    assert g.events[-1] == "teardown"


def test_nothing_approved_makes_no_changes_and_no_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    az, api = FakeAz(), FakeApi()
    code = g17.main(
        [*ARGS, "--evidence-dir", str(tmp_path), "--allow-external-evidence-dir"],
        runner=az,
        api=api,
    )
    assert code == 2
    assert [c[:2] for c in az.calls] == [["cloud", "show"]]  # nothing created
    assert api.log == []
    assert list(tmp_path.iterdir()) == []  # OPEN: no evidence is fabricated


def test_resume_skips_completed_steps(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    g1 = _gate(approve_all=False, approve={"provision", "diagnostics"}, state_file=state, keep=True)
    g17.run_gate(g1)
    assert json.loads(state.read_text(encoding="utf-8"))["completed"] == [
        "diagnostics",
        "provision",
    ]
    g2 = _gate(state_file=state, keep=True)
    code, ev = g17.run_gate(g2)
    assert code == 0
    assert "resume-skip:provision" in g2.events and "run:provision" not in g2.events
    assert ev["result"] == "PASS"


def test_echo_server_flag_prints_source(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    assert g17.main([*ARGS, "--print-echo-server"], runner=FakeAz(), api=FakeApi()) == 0
    assert "HTTPServer" in capsys.readouterr().out
