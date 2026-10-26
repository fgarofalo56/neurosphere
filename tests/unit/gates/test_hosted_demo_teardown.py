"""PRP-32 item 4: register-guarded teardown of scripts/gates/hosted_demo.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DEPLOYMENT_ID = "hosted-rg-ns-demo-test"


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


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.fixture
def env(tmp_path: Path) -> Any:
    return F.Env(tmp_path)


def _full_environment(env: Any) -> None:
    """Deploy, grant model access, redirect, seed access: everything teardown must undo."""
    assert env.deploy() == 0
    grant = ["--foundry-account-id", F.FOUNDRY, "--approve-shared", "foundry-role"]
    assert env.run("grant-model-access", *grant, infra=False) == 0
    redirect = ["--entra-client-id", F.APP_ID, "--approve-shared", "entra-app"]
    assert env.run("entra-redirect", *redirect, infra=False) == 0
    assert env.run("seed-access", "--grant", "--principal", F.OID_OPERATOR, infra=False) == 0
    env.fake.calls.clear()


def _teardown(env: Any, *extra: str) -> int:
    return env.run("teardown", *extra, infra=False)


@pytest.mark.parametrize("confirm", [[], ["--confirm", "wrong-id"], ["--confirm", ""]])
def test_teardown_refuses_without_the_right_confirm(env: Any, confirm: list[str]) -> None:
    _full_environment(env)
    assert _teardown(env, *confirm) == 2
    assert env.fake.index("group", "delete") == -1
    assert env.fake.index("webapp", "delete") == -1


def test_teardown_refuses_when_neither_register_copy_is_readable(env: Any) -> None:
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 2
    deleters = [c for c in env.fake.calls if "delete" in c[:4] or "remove" in c[:4]]
    assert deleters == []


def test_teardown_refuses_an_unregistered_resource_before_deleting_anything(env: Any) -> None:
    _full_environment(env)
    env.fake.live.append(
        {
            "id": F._rid("Microsoft.Storage/storageAccounts", "foreign"),
            "type": "Microsoft.Storage/x",
        }
    )
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 2
    deleters = [c for c in env.fake.calls if "delete" in c[:4] or "remove" in c[:4]]
    assert deleters == []
    assert env.fake.index("rest", "--method", "patch") == -1


def test_teardown_order_disconnects_vnet_before_any_site_delete(env: Any) -> None:
    _full_environment(env)
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    calls = env.fake.calls
    disconnects = [
        i for i, c in enumerate(calls) if c[:3] == ["webapp", "vnet-integration", "remove"]
    ]
    site_deletes = [i for i, c in enumerate(calls) if c[:2] == ["webapp", "delete"]]
    assert len(disconnects) == 3 and len(site_deletes) == 3
    assert max(disconnects) < min(site_deletes)
    first = {
        "entra": next(
            i for i, c in enumerate(calls) if c[:2] == ["rest", "--method"] and "patch" in c
        ),
        "foundry": next(
            i for i, c in enumerate(calls) if c[:3] == ["role", "assignment", "delete"]
        ),
        "pe": next(
            i for i, c in enumerate(calls) if c[:3] == ["network", "private-endpoint", "delete"]
        ),
        "plan": next(i for i, c in enumerate(calls) if c[:3] == ["appservice", "plan", "delete"]),
        "vault": next(i for i, c in enumerate(calls) if c[:2] == ["keyvault", "delete"]),
        "group": next(i for i, c in enumerate(calls) if c[:2] == ["group", "delete"]),
    }
    assert first["entra"] < first["foundry"] < min(disconnects)
    assert max(disconnects) < first["pe"] < min(site_deletes) < first["plan"] < first["vault"]
    assert first["vault"] < first["group"] == len(calls) - 1


def test_teardown_removes_api_private_endpoint_first(env: Any) -> None:
    _full_environment(env)
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    pes = [
        c[c.index("--ids") + 1]
        for c in env.fake.calls
        if c[:3] == ["network", "private-endpoint", "delete"]
    ]
    assert pes[0].endswith("nsdemo-api-pe") and len(pes) == 2


def test_teardown_restores_the_entra_redirect_list(env: Any) -> None:
    _full_environment(env)
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    assert env.fake.patches[-1] == {"spa": {"redirectUris": ["http://localhost:5173"]}}


def test_teardown_never_deletes_shared_resources_and_never_purges(env: Any) -> None:
    _full_environment(env)
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    shared = {m.lower() for m in (F.INTEG_SUBNET, F.PE_SUBNET, F.FOUNDRY, F.APP_OBJECT)}
    for call in env.fake.calls:
        is_delete = any(w in call[:5] for w in ("delete", "remove"))
        if is_delete:
            # A role assignment we created lives *under* the Foundry id; the account itself,
            # the subnets, zones and the Entra app object must never be a delete target.
            assert not any(arg.lower() in shared for arg in call)
            assert not any("privateDnsZones" in arg for arg in call)
            assert call[-1] != "purge" and "purge" not in call
    assert not any("purge" in c for c in env.fake.calls)
    deleted_role_ids = [
        c[c.index("--ids") + 1] for c in env.fake.calls if c[:3] == ["role", "assignment", "delete"]
    ]
    assert deleted_role_ids and all("/roleAssignments/" in r for r in deleted_role_ids)


def test_teardown_removes_budget_and_group_and_records_evidence(env: Any) -> None:
    _full_environment(env)
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    budget = [c for c in env.fake.calls if c[:1] == ["rest"] and "delete" in c]
    assert len(budget) == 1 and "Consumption/budgets" in budget[0][budget[0].index("--url") + 1]
    assert env.fake.count("group", "delete") == 1
    ev = env.evidence("teardown")
    assert ev["result"] == "PASS"
    assert any(s["step"] == "remove:resource-group" for s in ev["steps"])


def test_teardown_uses_the_cosmos_copy_when_the_local_one_is_gone(env: Any) -> None:
    _full_environment(env)
    (env.tmp / "state" / f"register-{DEPLOYMENT_ID}.json").unlink()
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    assert env.fake.count("group", "delete") == 1


def test_teardown_leaves_the_group_if_register_does_not_own_it(env: Any) -> None:
    _full_environment(env)
    rows = [
        r
        for r in env.backend.rows
        if not r.resource_id.lower().endswith(f"/resourcegroups/{F.RG}".lower())
    ]
    env.backend.rows = rows
    (env.tmp / "state" / f"register-{DEPLOYMENT_ID}.json").unlink()
    assert _teardown(env, "--confirm", DEPLOYMENT_ID) == 0
    assert env.fake.index("group", "delete") == -1
