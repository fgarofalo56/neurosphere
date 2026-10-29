"""G17 APIM observe gate: refusal, tokenisation, evidence shape, teardown guard, key hygiene.

Every test uses a fake `az` runner; no subprocess and no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g17_apim_observe_live.py"
SUB = "11111111-2222-3333-4444-555555555555"
FAKE_KEY = "k3y0123456789abcdef0123456789abcdef"
ENDPOINT = "https://example.openai.azure.com"
ARGS = ["--subscription", SUB, "--foundry-endpoint", ENDPOINT, "--foundry-deployment", "gpt"]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g17_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g17_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


g17 = _load()


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
        return g17.AzResult(0, out, "")


def _gate(az: FakeAz, **kw: Any) -> Any:
    g = g17.Gate(
        run_az=az,
        subscription=SUB,
        location="centralus",
        resource_group="ns-g17-t",
        foundry_endpoint=ENDPOINT,
        foundry_deployment="gpt",
        **kw,
    )
    g.sleep = lambda _s: None
    return g


def test_refuses_without_approval_and_makes_no_az_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    az = FakeAz()
    assert g17.main(ARGS, runner=az) == 2
    assert az.calls == []


def test_refuses_government_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    az = FakeAz()
    assert g17.main([*ARGS, "--location", "usgovvirginia"], runner=az) == 2
    assert az.calls == []


def test_tokenisation_of_subscription_and_resource_ids() -> None:
    ev = {"subscription": SUB, "apim_resource_id": f"/subscriptions/{SUB}/resourceGroups/r/x"}
    out = g17.redact(ev, subscriptions=[SUB], hosts=["example.openai.azure.com"])
    text = json.dumps(out)
    assert SUB not in text
    assert g17.subscription_token(SUB) in text
    assert out["apim_resource_id"].startswith(f"/subscriptions/{g17.subscription_token(SUB)}")


def test_evidence_shape_and_key_never_rendered(tmp_path: Path) -> None:
    az = FakeAz()
    g = _gate(az, approve_rbac=True, keep=True)
    g.sender = lambda _u, _h, _b: (200, {"x-ms-request-id": "corr-1"})
    g.observer = lambda _g: {"tier": "standard_v2", "inventory_counts": {"apis": 1}}
    g.row_fetcher = lambda _w, _m: [
        {"CorrelationId": "corr-1", "ApiId": "g17-llm", "TotalTokens": None}
    ]
    code, ev = g17.run_gate(g)
    assert code == 0
    assert ev["result"] == "PASS"
    assert ev["rbac"] == "applied"
    assert ev["llm_log_row"] == "not_observed"
    assert ev["paid_model_calls"] == 1
    assert [p["phase"] for p in ev["phases"]][:2] == ["1-create", "2-diagnostics"]
    assert all("status" in p and "duration_s" in p for p in ev["phases"])
    md = g17.write_evidence(ev, tmp_path, secrets=[FAKE_KEY])
    blob = md.read_text(encoding="utf-8") + md.with_suffix(".json").read_text(encoding="utf-8")
    assert FAKE_KEY not in blob
    assert SUB not in blob
    assert g._key == FAKE_KEY  # pyright: ignore[reportPrivateUsage]


def test_rbac_without_approval_is_skipped_and_tears_down() -> None:
    az = FakeAz()
    g = _gate(az)
    code, ev = g17.run_gate(g)
    assert code == 0
    assert ev["result"] == "PARTIAL_OPEN"
    assert ev["rbac"] == "skipped_awaiting_operator"
    assert ev["llm_log_row"] == "skipped"
    assert not any(c[:3] == ["role", "assignment", "create"] for c in az.calls)
    assert any(c[:2] == ["group", "delete"] for c in az.calls)


def test_teardown_refuses_untagged_resource() -> None:
    az = FakeAz(resources=[{"id": "/subscriptions/x/foreign", "tags": {}}])
    g = _gate(az)
    g.rg_created = True
    with pytest.raises(g17.TeardownRefusedError) as exc:
        g.teardown()
    assert exc.value.untagged == ["/subscriptions/x/foreign"]
    assert not any(c[:2] == ["group", "delete"] for c in az.calls)
