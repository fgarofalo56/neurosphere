"""PRP-71 item 6: the demo check logic (``sbx_demo_check.py``) against a fake client.

No network, no Docker, no stack: every API answer is canned. The route -> calls map is the real
one (``manifest_calls.py``), loaded the way the check loads it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "sandbox"
TOKEN = "tok-SENTINEL-do-not-print-0123456789"
DOMAIN = "commercial:synthco:finance"


def _load() -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "sbx_demo_check_under_test", SCRIPTS / "sbx_demo_check.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()
CONTROL = check.customer_control_domain("commercial", "synthco")
calls_module = check.load_calls()
ApiCall = calls_module.ApiCall


class FakeClient:
    """Answers by path (query ignored). Unknown paths are 404."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.answers: dict[str, Any] = {
            "/api/v1/me/domains": {"items": [{"domain_id": DOMAIN}, {"domain_id": CONTROL}]},
        }
        self.answers.update(answers or {})
        self.paths: list[str] = []

    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Any:
        self.paths.append(path)
        answer = self.answers.get(path)
        if answer is None:
            return check.Reply(404, {"reason": "not_found"})
        if isinstance(answer, check.Reply):
            return answer
        return check.Reply(200, answer)


COST = "/api/v1/dashboards/domains/{domain}/cost"
COST_PATH = COST.replace("{domain}", DOMAIN)
CALLS = {"/page": (ApiCall(COST, non_empty="series"),)}


def _routes(
    answers: dict[str, Any],
    allow: dict[str, Any] | None = None,
    routes: Sequence[str] = ("/page",),
) -> dict[str, Any]:
    client = FakeClient(answers)
    domains = check.discover_domains(client)
    results = check.check_routes(client, routes, CALLS, domains, allow or {})
    return {r.route: r for r in results}


def test_a_route_with_data_passes() -> None:
    result = _routes({COST_PATH: {"series": [1]}})["/page"]
    assert (result.state, result.ok) == (check.DATA, True)


def test_the_control_domain_is_not_asked_for_data() -> None:
    client = FakeClient({COST_PATH: {"series": [1]}})
    check.check_routes(client, ["/page"], CALLS, check.discover_domains(client), {})
    assert all(CONTROL not in p for p in client.paths)


def test_an_unexplained_empty_route_fails() -> None:
    result = _routes({COST_PATH: {"series": []}})["/page"]
    assert (result.state, result.ok) == (check.EMPTY, False)


def test_an_allow_listed_empty_route_passes_and_shows_its_reason() -> None:
    allow = {"/page": check.AllowedEmpty("no cost rows by design", "PRP-99")}
    result = _routes({COST_PATH: {"series": []}}, allow)["/page"]
    assert (result.state, result.ok) == (check.ALLOWED_EMPTY, True)
    report = check.Report(routes=[result])
    text = check.render(report)
    assert "no cost rows by design" in text
    assert "PRP-99" in text


def test_an_allow_listed_route_that_has_data_fails() -> None:
    allow = {"/page": check.AllowedEmpty("was empty", "PRP-99")}
    result = _routes({COST_PATH: {"series": [1]}}, allow)["/page"]
    assert (result.state, result.ok) == (check.STALE_ALLOW, False)


def test_an_allow_list_entry_naming_no_route_fails() -> None:
    allow = {"/gone": check.AllowedEmpty("was empty", "PRP-99")}
    results = _routes({COST_PATH: {"series": [1]}}, allow)
    assert results["/gone"].state == check.STALE_ALLOW


def test_an_unmapped_route_fails() -> None:
    results = _routes({COST_PATH: {"series": [1]}}, routes=("/page", "/brand-new"))
    assert (results["/brand-new"].state, results["/brand-new"].ok) == (check.UNMAPPED, False)


def test_a_non_200_route_fails_with_the_status() -> None:
    result = _routes({COST_PATH: check.Reply(500, {"reason": "boom"})})["/page"]
    assert result.state == check.ERROR
    assert "500" in result.detail


def test_the_forecast_409_is_an_expected_answer() -> None:
    key = next(iter(check.EXPECTED_STATUS))
    path = key.split("?")[0].replace("{domain}", DOMAIN)
    call = ApiCall(
        "/api/v1/finops/domains/{domain}/forecast",
        (
            ("history_days", "30"),
            ("horizon_days", "30"),
            ("currency", "USD"),
        ),
        non_empty="series",
    )
    client = FakeClient({path: check.Reply(409, {"reason": "price_version_unresolved"})})
    results = check.check_routes(
        client, ["/f"], {"/f": (call,)}, check.discover_domains(client), {}
    )
    assert results[0].state == check.SERVED


def test_every_manifest_route_is_mapped() -> None:
    manifest = check.load_manifest_routes()
    assert sorted(set(manifest) - set(calls_module.MANIFEST_CALLS)) == []


def test_expected_status_matches_the_real_stack_suite() -> None:
    source = (ROOT / "tests/integration/real_stack/test_manifest_routes.py").read_text("utf-8")
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "EXPECTED_STATUS"
            and node.value is not None
        ):
            literal = ast.literal_eval(node.value)
            assert {k: v[0] for k, v in literal.items()} == check.EXPECTED_STATUS
            return
    pytest.fail("EXPECTED_STATUS not found in test_manifest_routes.py")


# -- allow-list ledger -----------------------------------------------------------------------


def test_every_allow_list_entry_has_a_reason_and_an_owning_prp() -> None:
    for route, entry in check.demo_expected_empty.items():
        assert route.startswith("/"), route
        assert len(entry.reason.strip()) >= 10, route
        assert re.fullmatch(r"PRP-\d+", entry.owner_prp), route


# -- features and copilot --------------------------------------------------------------------


def _status(**states: str) -> dict[str, Any]:
    names = {"admin_producers": "ok", "mcp_server": "ok", "scan": "ok", "copilot": "disabled"}
    names.update(states)
    return {
        "ready": True,
        "components": [{"name": n, "state": s} for n, s in names.items()],
        "probes": {},
        "stored_settings": {"status": "loaded", "reason": None, "invalid_keys": []},
    }


def _features(
    status: dict[str, Any] | None = None,
    mode: str = "disabled",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answers: dict[str, Any] = {
        check.STATUS_PATH: _status() if status is None else status,
        check.LIFECYCLE_PATH: {"mode": "dry_run", "policy_status": "set"},
        check.COPILOT_PATH: check.Reply(503, {"reason": "copilot_unconfigured"}),
    }
    answers.update(extra or {})
    return {f.name: f for f in check.check_features(FakeClient(answers), mode)}


def test_a_fully_enabled_demo_passes_the_feature_check() -> None:
    features = _features()
    assert all(f.ok for f in features.values()), features
    assert features["lifecycle"].state == check.ENABLED


@pytest.mark.parametrize(
    ("override", "feature"),
    [
        ({"admin_producers": "disabled"}, "producer_store"),
        ({"mcp_server": "disabled"}, "mcp_server"),
        ({"scan": "disabled"}, "scan"),
        ({"scan": "failed"}, "scan"),
    ],
)
def test_a_disabled_component_feature_fails(override: dict[str, str], feature: str) -> None:
    features = _features(_status(**override))
    assert (features[feature].state, features[feature].ok) == (check.DISABLED, False)


def test_unconfigured_lifecycle_fails() -> None:
    answers = {
        check.STATUS_PATH: _status(),
        check.LIFECYCLE_PATH: check.Reply(503, {"reason": "lifecycle_unconfigured"}),
        check.COPILOT_PATH: check.Reply(503, {"reason": "copilot_unconfigured"}),
    }
    result = {f.name: f for f in check.check_features(FakeClient(answers), "disabled")}
    assert (result["lifecycle"].state, result["lifecycle"].ok) == (check.DISABLED, False)


def test_lifecycle_in_execute_mode_is_unexpected() -> None:
    features = _features(extra={check.LIFECYCLE_PATH: {"mode": "execute"}})
    assert not features["lifecycle"].ok


def test_unloaded_stored_settings_fail() -> None:
    status = _status()
    status["stored_settings"] = {"status": "unconfigured", "reason": "x", "invalid_keys": []}
    assert not _features(status)["stored_settings"].ok


def test_unreported_features_are_listed_not_guessed() -> None:
    features = _features()
    for name in ("detector_archive_source", "connector_roles"):
        assert features[name].state == check.NOT_REPORTED
        assert features[name].ok


def test_copilot_is_pending_prp_78_while_disabled() -> None:
    copilot = _features()["copilot"]
    assert copilot.state == check.PENDING_PRP_78
    assert copilot.ok  # neither a pass nor a failure
    assert "pending_prp_78" in check.render(check.Report(features=[copilot]))


def test_copilot_with_the_wrong_disabled_shape_fails() -> None:
    features = _features(extra={check.COPILOT_PATH: check.Reply(200, {"items": []})})
    assert (features["copilot"].state, features["copilot"].ok) == (check.UNEXPECTED, False)


def test_copilot_on_needs_its_component() -> None:
    on = _features(_status(copilot="ok"), mode="recorded")["copilot"]
    off = _features(_status(copilot="disabled"), mode="recorded")["copilot"]
    assert on.state == check.ENABLED
    assert off.state == check.DISABLED


def test_an_unreadable_status_route_fails() -> None:
    features = _features(extra={check.STATUS_PATH: check.Reply(403, {"reason": "forbidden"})})
    assert [f.ok for f in features.values()] == [False]


# -- demo-world sanity -----------------------------------------------------------------------

WORLD = check.build_demo_world("commercial")


def _entity(identifier: str) -> dict[str, Any]:
    return {"id": identifier}


def _world_answers(health: dict[str, str] | None = None, drop: str | None = None) -> dict[str, Any]:
    agents = [_entity(a["id"]) for a in WORLD.agents if not a["id"].endswith(f":{drop}")]
    drafts = [_entity(a.agent_id) for a in WORLD.undeclared_agents]
    nodes = [
        {
            "id": i,
            "kind": "agent",
            "metrics": {"health": (health or {}).get(i.rsplit(":", 1)[-1], "ok")},
        }
        for i in (*(a["id"] for a in WORLD.agents), *WORLD.undeclared_agent_ids)
    ]

    return {
        "agents": agents,
        "drafts": drafts,
        "viewport": {"nodes": nodes, "edges": []},
    }


class WorldClient(FakeClient):
    def __init__(self, parts: dict[str, Any]) -> None:
        super().__init__()
        self.parts = parts

    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Any:
        if path == check.ENTITIES_PATH:
            draft = ("lifecycle", "draft") in query
            return check.Reply(200, {"items": self.parts["drafts" if draft else "agents"]})
        if path.endswith("/viewport"):
            return check.Reply(200, self.parts["viewport"])
        return super().get(path, query, persona)


def _downstream_health(state: str) -> dict[str, str]:
    return {i.rsplit(":", 1)[-1]: state for i in WORLD.downstream_agent_ids}


def _world(parts: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    clock = iter(range(0, 10_000, 10))
    results = check.check_world(
        WorldClient(parts),
        [DOMAIN],
        WORLD,
        wait_seconds=30,
        poll_seconds=1,
        sleep=lambda _s: None,
        clock=lambda: float(next(clock)),
        **kwargs,
    )
    return {r.name: r for r in results}


def test_the_demo_world_passes_when_the_outage_shows() -> None:
    results = _world(_world_answers(_downstream_health("degraded")))
    assert all(r.state == check.PASSED for r in results.values()), results


def test_a_missing_curated_agent_fails() -> None:
    results = _world(_world_answers(_downstream_health("failing"), drop="journal-entry-agent"))
    assert results["curated_agents_present"].state == check.FAIL
    assert "journal-entry-agent" in results["curated_agents_present"].detail


def test_healthy_downstream_agents_fail_after_the_bounded_wait() -> None:
    results = _world(_world_answers())
    assert results["outage_downstream_health"].state == check.FAIL


def test_unknown_health_is_reported_not_checked() -> None:
    health = {a["id"].rsplit(":", 1)[-1]: "unknown" for a in WORLD.agents}
    results = _world(_world_answers(health))
    assert results["outage_downstream_health"].state == check.NOT_CHECKED


def test_missing_undeclared_drafts_fail() -> None:
    parts = _world_answers(_downstream_health("degraded"))
    parts["drafts"] = parts["drafts"][:2]
    assert _world(parts)["undeclared_agents_discovered"].state == check.FAIL


# -- guards, output and the whole run --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://10.1.2.3:8000",
        "https://contoso.azurewebsites.net",
        "http://127.0.0.1.evil.example:8000",
        "ftp://127.0.0.1:8000",
    ],
)
def test_a_non_loopback_api_is_refused(url: str) -> None:
    with pytest.raises(check.GuardError):
        check.guard_environment(url, {})


def test_loopback_is_accepted_and_a_remote_cosmos_is_refused() -> None:
    assert check.guard_environment("http://127.0.0.1:8000/", {}) == "http://127.0.0.1:8000"
    with pytest.raises(check.GuardError):
        check.guard_environment(
            "http://127.0.0.1:8000", {"NS_COSMOS_ENDPOINT": "https://acct.documents.azure.com"}
        )
    with pytest.raises(check.GuardError):
        check.guard_environment("http://127.0.0.1:8000", {"NS_ENV": "prod"})


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "operator.token"
    path.write_text(TOKEN, encoding="utf-8")
    return path


def test_main_refuses_a_non_loopback_url_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = check.main(
        ["--base-url", "http://203.0.113.9:8000", "--token-file", str(_token_file(tmp_path))],
        env={},
        client_factory=lambda *_: pytest.fail("the client must not be built"),
    )
    captured = capsys.readouterr()
    assert code == check.EXIT_REFUSED
    assert TOKEN not in captured.out + captured.err


def test_main_without_a_token_exits_2() -> None:
    assert check.main([], env={}) == check.EXIT_REFUSED


class _PassingClient(FakeClient):
    """Every manifest route has data; every feature is on; the world is as seeded."""

    def __init__(self, seen_tokens: list[str], token: str) -> None:
        super().__init__()
        seen_tokens.append(token)

    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Any:
        if path == check.DOMAINS_PATH:
            return check.Reply(200, {"items": [{"domain_id": DOMAIN}]})
        if path == check.STATUS_PATH:
            return check.Reply(200, _status())
        if path == check.LIFECYCLE_PATH:
            return check.Reply(200, {"mode": "dry_run"})
        if path == check.COPILOT_PATH:
            return check.Reply(503, {"reason": "copilot_unconfigured"})
        if path == check.ENTITIES_PATH:
            draft = ("lifecycle", "draft") in query
            items = (
                [_entity(a.agent_id) for a in WORLD.undeclared_agents]
                if draft
                else [_entity(a["id"]) for a in WORLD.agents]
            )
            return check.Reply(200, {"items": items})
        if path.endswith("/viewport"):
            health = _downstream_health("failing")
            nodes = [
                {
                    "id": a["id"],
                    "kind": "agent",
                    "metrics": {"health": health.get(a["id"].rsplit(":", 1)[-1], "ok")},
                }
                for a in WORLD.agents
            ]
            return check.Reply(
                200, {"nodes": nodes, "edges": [], "coverage": {"state": "complete"}}
            )
        return check.Reply(200, _generic_body())


def _generic_body() -> dict[str, Any]:
    fields = (
        "items",
        "series",
        "coverage",
        "nodes",
        "intent",
        "id",
        "spans",
        "recommendation",
        "item_id",
        "server_id",
    )
    return {name: [1] for name in fields}


def test_a_whole_passing_run_exits_0_and_never_prints_the_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    argv = ["--token-file", str(_token_file(tmp_path)), "--wait-seconds", "1"]
    code = check.main(argv, env={}, client_factory=lambda _base, token: _PassingClient(seen, token))
    out = capsys.readouterr()
    assert code == 0, out.out
    assert seen == [TOKEN]  # the token reached the client factory only
    assert TOKEN not in out.out + out.err
    assert "pending_prp_78" in out.out
    assert "PASS" in out.out


def test_json_output_is_parseable_and_token_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = check.main(
        ["--json", "--token-file", str(_token_file(tmp_path)), "--wait-seconds", "1"],
        env={},
        client_factory=lambda _base, token: _PassingClient([], token),
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    assert code == 0
    assert report["ok"] is True
    assert TOKEN not in out
    assert {r["route"] for r in report["routes"]} == set(check.load_manifest_routes())


def test_a_failing_run_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    class Empty(_PassingClient):
        def get(
            self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
        ) -> Any:
            if path.startswith("/api/v1/dashboards/"):
                return check.Reply(200, {"series": []})
            return super().get(path, query, persona)

    code = check.main(
        ["--token-file", str(_token_file(tmp_path)), "--wait-seconds", "1"],
        env={},
        client_factory=lambda _base, token: Empty([], token),
    )
    out = capsys.readouterr().out
    assert code == check.EXIT_FAILED
    assert "FAIL" in out
    assert TOKEN not in out


def test_the_http_client_repr_hides_the_token() -> None:
    client = check.HttpClient("http://127.0.0.1:1", TOKEN)
    try:
        assert TOKEN not in repr(client)
    finally:
        client.close()


def test_an_empty_report_is_not_ok() -> None:
    assert not check.Report().ok
