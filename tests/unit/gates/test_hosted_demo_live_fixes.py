"""PRP-32 item 11: fixes found in the live run of hosted_demo.py (role ids, KV refresh, revoke)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _fakes() -> ModuleType:
    name = "hosted_demo_fakes"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("test_hosted_demo_refuses.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _fakes()
ROLE_PREFIX = f"/subscriptions/{F.SUB}/providers/Microsoft.Authorization/roleDefinitions/"


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.fixture
def env(tmp_path: Path) -> Any:
    return F.Env(tmp_path)


def _seed(env: Any, flag: str) -> int:
    return env.run("seed-access", flag, "--principal", F.OID_OPERATOR, infra=False)


def _rbac_calls(env: Any, verb: str) -> list[list[str]]:
    return [c for c in env.fake.calls if c[:3] == ["role", "assignment", verb]]


def _seed_rows(env: Any) -> list[Any]:
    return [r for r in env.backend.rows if r.service == "seed-access"]


# ------------------------------------------------------------------ (a) full role-definition id


def test_seed_rbac_passes_full_role_definition_id_at_container_scope(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.calls.clear()
    assert _seed(env, "--grant") == 0
    for verb in ("list", "create"):
        calls = _rbac_calls(env, verb)
        assert len(calls) == 3
        for c in calls:
            role = c[c.index("--role") + 1]
            assert role.startswith(ROLE_PREFIX)
            assert role.removeprefix(ROLE_PREFIX) and "/" not in role.removeprefix(ROLE_PREFIX)
    container = [c for c in _rbac_calls(env, "create") if "/containers/archive" in " ".join(c)]
    assert len(container) == 1


# ------------------------------------------------------------------ (b) KV reference refresh


def test_deploy_that_creates_the_secret_refreshes_then_restarts_both_sites(env: Any) -> None:
    assert env.deploy() == 0
    calls = env.fake.calls
    posts = [
        i
        for i, c in enumerate(calls)
        if c[0] == "rest" and "post" in c and "configreferences/appsettings/refresh" in c[-3]
    ]
    assert len(posts) == 2
    assert all("api-version=2022-03-01" in calls[i][calls[i].index("--url") + 1] for i in posts)
    urls = [calls[i][calls[i].index("--url") + 1] for i in posts]
    assert any("/sites/nsdemo-api/" in u for u in urls)
    assert any("/sites/nsdemo-workers/" in u for u in urls)
    restarts = [i for i, c in enumerate(calls) if c[:2] == ["webapp", "restart"]]
    assert len(restarts) == 2
    assert all(
        "--subscription" in calls[i] for i in restarts
    )  # explicit subscription on every call
    assert min(restarts) > min(posts)
    assert env.fake.index("keyvault", "secret", "set") < min(posts)
    gets = [
        c
        for c in calls
        if c[0] == "rest" and "get" in c and "api-version=2023-12-01" in c[c.index("--url") + 1]
    ]
    assert len(gets) == 2


def test_deploy_fails_the_step_on_an_unresolved_reference_naming_setting_and_status(
    env: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    env.fake.ref_statuses["NS_AUTH_PSEUDONYM_KEY"] = "SecretNotFound"
    assert env.deploy() == 1
    steps = env.evidence("deploy")["steps"]
    failed = [s for s in steps if s["step"].startswith("kv-refs:") and s["status"] == "failed"]
    assert failed
    assert "NS_AUTH_PSEUDONYM_KEY=SecretNotFound" in failed[0]["detail"]
    assert "NS_ARCHIVE_PSEUDONYM_KEY" not in failed[0]["detail"]
    assert env.fake.secret_seen not in capsys.readouterr().out


def test_deploy_with_the_secret_already_present_makes_no_refresh_call(env: Any) -> None:
    env.fake.kv_names = ["pseudonym-key"]
    assert env.deploy() == 0
    assert not any("configreferences" in " ".join(c) for c in env.fake.calls)
    assert env.fake.index("webapp", "restart") == -1


# ------------------------------------------------------------------ (c) register-bound revoke


def test_revoke_deletes_only_registered_assignments_and_drops_their_rows(
    env: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert env.deploy() == 0
    assert _seed(env, "--grant") == 0
    assert len(_seed_rows(env)) == 4
    container = next(r for r in env.fake.rbac_live if "/containers/archive/" in r)
    foreign = container.rsplit("/", 1)[0] + "/ffffffff-0000-0000-0000-000000000009"
    env.fake.rbac_live.append(foreign)
    foreign_cosmos = {
        "id": f"{F.BASE}/Microsoft.DocumentDB/databaseAccounts/nsdemocosmos/sqlRoleAssignments/"
        "ffffffff-0000-0000-0000-000000000008",
        "principalId": F.OID_OPERATOR,
        "roleDefinitionId": env.fake.cosmos_assignments[0]["roleDefinitionId"],
        "scope": "/dbs/neurosphere",
    }
    env.fake.cosmos_assignments.append(foreign_cosmos)
    env.fake.calls.clear()
    capsys.readouterr()

    assert _seed(env, "--revoke") == 0

    deleted = [c[c.index("--ids") + 1] for c in _rbac_calls(env, "delete")]
    assert len(deleted) == 3 and foreign not in deleted
    assert env.fake.rbac_live == [foreign]
    assert [r["id"] for r in env.fake.cosmos_assignments] == [foreign_cosmos["id"]]
    assert env.fake.count("cosmosdb", "sql", "role", "assignment", "delete") == 1
    assert _seed_rows(env) == []
    out = capsys.readouterr().out
    assert "removed 1" in out and "removed 0" not in out


def test_revoke_reports_zero_when_nothing_is_registered(
    env: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert env.deploy() == 0
    assert _seed(env, "--grant") == 0
    env.backend.rows = [r for r in env.backend.rows if r.service != "seed-access"]
    state = next((env.tmp / "state").glob("register-*.json"))
    export = F.json.loads(state.read_text(encoding="utf-8"))
    export["rows"] = [r for r in export["rows"] if r["service"] != "seed-access"]
    state.write_text(F.json.dumps(export), encoding="utf-8")
    env.fake.calls.clear()
    capsys.readouterr()

    assert _seed(env, "--revoke") == 0

    assert _rbac_calls(env, "delete") == []
    assert env.fake.count("cosmosdb", "sql", "role", "assignment", "delete") == 0
    assert len(env.fake.rbac_live) == 3 and len(env.fake.cosmos_assignments) == 1
    out = capsys.readouterr().out
    assert "removed 0 (none registered)" in out
    assert "role assignment removed" not in out
