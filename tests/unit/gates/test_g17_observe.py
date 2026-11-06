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


def test_extra_tags_reach_the_group_and_workspace_creates() -> None:
    az = FakeAz()
    g = _gate(az, extra_tags=("project=neurosphere", "owner=g17-gate-operator"))
    g.create_infra()
    creates = [
        c
        for c in az.calls
        if c[:2] == ["group", "create"] or c[:3] == ["monitor", "log-analytics", "workspace"]
    ]
    assert len(creates) == 2
    group, workspace = creates
    group_tags = group[group.index("--tags") + 1 :]
    assert "project=neurosphere" in group_tags
    assert "owner=g17-gate-operator" in group_tags
    assert g17.CREATED_BY_TAG in group_tags
    # The workspace create parses --tags as shorthand, which rejects the colon in the key, so it
    # gets one JSON object (a live run failed here before this was a JSON object).
    ws_tags = json.loads(workspace[workspace.index("--tags") + 1])
    assert ws_tags == {
        "neurosphere:created-by": "g17",
        "neurosphere:gate": "G17",
        "project": "neurosphere",
        "owner": "g17-gate-operator",
    }


def test_rest_reads_a_bom_prefixed_response_from_the_output_file() -> None:
    # A live run failed in phase 3: az printed a non-JSON response starting with a BOM and died on
    # the cp1252 console encoding. rest() now has az write the payload to a file instead.
    class BomAz(FakeAz):
        def __call__(self, args: Sequence[str]) -> Any:
            a = list(args)
            if a[:1] == ["rest"] and "--output-file" in a:
                Path(a[a.index("--output-file") + 1]).write_bytes(b"\xef\xbb\xbf" + b'{"ok": 1}')
                self.calls.append(a)
                return g17.AzResult(0, "", "")
            return super().__call__(args)

    az = BomAz()
    g = _gate(az)
    assert g.rest("GET", "/x", None, "2024-05-01") == {"ok": 1}
    assert "--output-file" in az.calls[-1]
    assert not Path(az.calls[-1][az.calls[-1].index("--output-file") + 1]).exists()


def test_request_retries_while_role_and_key_propagate_then_succeeds() -> None:
    # Live run 5: the first gateway call was a 401, seconds after the role assignment.
    statuses = iter([401, 401, 403, 200])
    seen: list[int] = []

    def sender(_u: str, _h: dict[str, str], _b: dict[str, Any]) -> tuple[int, dict[str, str]]:
        status = next(statuses)
        seen.append(status)
        return status, {"x-ms-request-id": "corr-1"}

    sleeps: list[float] = []
    g = _gate(FakeAz())
    g.sender = sender
    g.sleep = sleeps.append
    out = g.send_request()
    assert seen == [401, 401, 403, 200]
    assert out["attempts"] == 4
    assert out["paid_model_calls"] == 1
    assert sleeps == [g17.REQUEST_RETRY_DELAY_S] * 3


def test_observe_timeout_says_what_the_last_query_saw() -> None:
    # Live run 8 polled for 20 minutes and failed with no way to tell "table never appeared" from
    # "table exists, no matching row".
    ticks = iter([0.0, 1.0, 10_000_000.0])
    g = _gate(FakeAz())
    g.clock = lambda: next(ticks)
    g.facts["workspace_customer_id"] = "ws"
    g.facts["last_query_note"] = "table not ready: Failed to resolve table"
    g.row_fetcher = lambda _w, _m: []
    with pytest.raises(g17.GateError, match=r"last query: table not ready"):
        g.observe()


def test_query_response_table_becomes_row_dicts() -> None:
    payload = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [{"name": "CorrelationId", "type": "string"}, {"name": "TotalTokens"}],
                "rows": [["c-1", 12], ["c-2", None]],
            }
        ]
    }
    assert g17.rows_from_query_response(payload) == [
        {"CorrelationId": "c-1", "TotalTokens": 12},
        {"CorrelationId": "c-2", "TotalTokens": None},
    ]
    assert g17.rows_from_query_response(None) == []
    assert g17.rows_from_query_response({"tables": []}) == []


def test_a_missing_table_is_not_ready_but_other_errors_are_not() -> None:
    # A new workspace has no ApiManagementGatewayLogs table until the first ingestion.
    assert g17.is_table_not_ready_error("SemanticError: Failed to resolve table 'X'")
    assert g17.is_table_not_ready_error("BadArgumentError")
    assert not g17.is_table_not_ready_error("AuthorizationFailed: no access")


def test_stderr_noise_from_az_extensions_is_dropped() -> None:
    noise = (
        "C:\\Users\\x\\.azure\\cliextensions\\monitor-control-service\\_create.py:21: "
        'SyntaxWarning: "\\s"\n'
        '  az monitor data-collection rule create --resource-group "r"\n'
        "ERROR: HTTPSConnection(host='api.loganalytics.io'): Failed to resolve\n"
    )
    cleaned = g17.clean_stderr(noise)
    assert "SyntaxWarning" not in cleaned
    assert cleaned.startswith("ERROR: HTTPSConnection")


def test_request_uses_max_completion_tokens_and_reports_the_server_error() -> None:
    # Live run 6: HTTP 400 with no reason. gpt-5 models reject max_tokens, and the error text was
    # discarded; now the body uses max_completion_tokens and a failure carries the server message.
    bodies: list[dict[str, Any]] = []

    def sender(_u: str, _h: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, str]]:
        bodies.append(body)
        return 400, {g17.ERROR_BODY_HEADER: "Unsupported parameter: 'x'"}

    g = _gate(FakeAz())
    g.sender = sender
    with pytest.raises(g17.GateError, match=r"HTTP 400 after 1 attempt.*Unsupported parameter"):
        g.send_request()
    assert "max_tokens" not in bodies[0]
    assert bodies[0]["max_completion_tokens"] == g17.MAX_COMPLETION_TOKENS


def test_request_gives_up_after_the_retry_budget_and_never_retries_other_errors() -> None:
    g = _gate(FakeAz())
    g.sleep = lambda _s: None
    g.sender = lambda _u, _h, _b: (401, {})
    with pytest.raises(g17.GateError, match="HTTP 401 after 12 attempt"):
        g.send_request()
    calls: list[int] = []

    def server_error(_u: str, _h: dict[str, str], _b: dict[str, Any]) -> tuple[int, dict[str, str]]:
        calls.append(500)
        return 500, {}

    g2 = _gate(FakeAz())
    g2.sleep = lambda _s: None
    g2.sender = server_error
    with pytest.raises(g17.GateError, match="HTTP 500 after 1 attempt"):
        g2.send_request()
    assert calls == [500]


def test_rest_returns_non_json_text_for_an_xml_policy_response() -> None:
    # Live run 4: the policy PUT answered with policy XML and json.loads raised, failing phase 3.
    class XmlAz(FakeAz):
        def __call__(self, args: Sequence[str]) -> Any:
            a = list(args)
            if a[:1] == ["rest"] and "--output-file" in a:
                Path(a[a.index("--output-file") + 1]).write_bytes(
                    b"\xef\xbb\xbf<policies><inbound><base /></inbound></policies>"
                )
                self.calls.append(a)
                return g17.AzResult(0, "", "")
            return super().__call__(args)

    g = _gate(XmlAz())
    out = g.rest("PUT", "/policies/policy", {"properties": {"format": "rawxml"}}, "2024-05-01")
    assert isinstance(out, str)
    assert out.startswith("<policies>")


def test_malformed_tag_is_refused_before_any_resource_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    az = FakeAz()
    assert g17.main([*ARGS, "--tag", "no-equals-sign"], runner=az) == 2
    assert not any(c[:2] == ["group", "create"] for c in az.calls)


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


def test_evidence_dir_stays_inside_repo_unless_overridden(tmp_path: Path) -> None:
    inside = g17.REPO / "docs" / "evidence" / "G17"
    assert g17.evidence_dir_for(str(inside)) == inside.resolve()
    assert (
        g17.evidence_dir_for(str(g17.REPO / "docs" / ".." / "temp"))
        == (g17.REPO / "temp").resolve()
    )
    with pytest.raises(g17.EvidenceDirRefusedError):
        g17.evidence_dir_for(str(tmp_path))
    with pytest.raises(g17.EvidenceDirRefusedError):
        g17.evidence_dir_for(str(g17.REPO.parent))
    assert g17.evidence_dir_for(str(tmp_path), allow_external=True) == tmp_path.resolve()
