"""access-plan: the table, the az lines, the hash; offline, no Azure write (PRP-139 item 6)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "hosted_real_tenant.py"
SUB = "00000000-0000-0000-0000-000000000001"
WORKERS = "00000000-0000-0000-0000-0000000000aa"
API = "00000000-0000-0000-0000-0000000000bb"
RG = f"/subscriptions/{SUB}/resourceGroups/rg-fake/providers"
FOUNDRY = f"{RG}/Microsoft.CognitiveServices/accounts/fake-account"
WORKSPACE = f"{RG}/Microsoft.OperationalInsights/workspaces/fake-law"
APIM = f"{RG}/Microsoft.ApiManagement/service/fake-apim"
STORAGE = f"{RG}/Microsoft.Storage/storageAccounts/fakestorage"


def load() -> ModuleType:
    name = "hosted_real_tenant_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def registration(tmp_path: Path, **extra: object) -> Path:
    doc = {
        "schema": 1,
        "deployment_id": "fake-deploy",
        "cloud": "AzureCloud",
        "workers_object_id": WORKERS,
        "customer_id": "fakecust",
        **extra,
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def plan_args(tmp_path: Path, reg: Path) -> list[str]:
    return [
        "access-plan",
        "--registration",
        str(reg),
        "--plan-file",
        str(tmp_path / "plan.json"),
        "--api-principal-id",
        API,
        "--foundry-account-ids",
        FOUNDRY,
        "--log-analytics-workspace-ids",
        WORKSPACE,
        "--apim-service-ids",
        APIM,
        "--billing-export-storage-account-id",
        STORAGE,
    ]


def test_plan_rows_and_verified_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = load()
    calls: list[object] = []

    def az(args: object) -> object:  # pragma: no cover - must never run
        calls.append(args)
        raise AssertionError("access-plan must not call az")

    assert mod.main(plan_args(tmp_path, registration(tmp_path)), env={}, az_runner=az) == 0
    assert calls == []
    out = capsys.readouterr().out
    doc = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    rows = doc["rows"]
    by_role = {r["role_name"]: r for r in rows}
    assert len(rows) == 5
    assert by_role["Foundry User (formerly Azure AI User)"]["role_definition_id"] == (
        "53ca6127-db72-4b80-b1b0-d745d6d5456d"
    )
    assert by_role["Storage Blob Data Reader"]["role_definition_id"] == (
        "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
    )
    assert by_role["Log Analytics Data Reader"]["role_definition_id"] == (
        "3b03c2da-16b3-4a49-8834-0f8130efdd3b"
    )
    assert by_role["API Management Service Reader Role"]["identity"] == "api"
    assert by_role["Storage Blob Data Reader"]["identity"] == "workers"
    # Every scope is one resource; the az lines carry the full role definition id.
    assert {r["scope"] for r in rows} == {FOUNDRY, WORKSPACE, APIM, STORAGE}
    assert f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/" in out
    assert "az " in out and "role" in out and "assignment" in out
    assert doc["plan_hash"] in out


def test_unverified_row_is_printed_and_has_no_token_or_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load()
    assert mod.main(plan_args(tmp_path, registration(tmp_path)), env={}) == 0
    out = capsys.readouterr().out
    rows = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))["rows"]
    unverified = [r for r in rows if not r["verified"]]
    assert len(unverified) == 1
    assert unverified[0]["token"] == ""
    assert "UNVERIFIED" in out
    assert "Monitoring Reader" in out
    assert out.count("az role assignment create") == 4


def test_plan_hash_is_stable_and_changes_with_content(tmp_path: Path) -> None:
    mod = load()
    reg = registration(tmp_path)
    mod.main(plan_args(tmp_path, reg), env={})
    first = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))["plan_hash"]
    mod.main(plan_args(tmp_path, reg), env={})
    assert json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))["plan_hash"] == first
    args = plan_args(tmp_path, reg)
    args[args.index("--foundry-account-ids") + 1] = FOUNDRY.replace("fake-account", "other")
    mod.main(args, env={})
    assert json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))["plan_hash"] != first


@pytest.mark.parametrize(
    "scope",
    [
        f"/subscriptions/{SUB}",
        f"/subscriptions/{SUB}/resourceGroups/rg-fake",
        "/providers/Microsoft.Management/managementGroups/mg-fake",
        f"{FOUNDRY}/projects/p1",
        WORKSPACE,  # right shape, wrong type for the Foundry flag
    ],
)
def test_plan_refuses_non_single_resource_scope(tmp_path: Path, scope: str) -> None:
    mod = load()
    args = plan_args(tmp_path, registration(tmp_path))
    args[args.index("--foundry-account-ids") + 1] = scope
    assert mod.main(args, env={}) == 2
    assert not (tmp_path / "plan.json").exists()


def test_plan_refuses_government_registration(tmp_path: Path) -> None:
    mod = load()
    reg = registration(tmp_path, cloud="AzureUSGovernment")
    assert mod.main(plan_args(tmp_path, reg), env={}) == 2
    assert not (tmp_path / "plan.json").exists()


def test_plan_refuses_government_env_with_real_tenant_mode(tmp_path: Path) -> None:
    mod = load()
    env = {"NS_CLOUD": "government", "NS_HOSTED_DATA_MODE": "real-tenant"}
    assert mod.main(plan_args(tmp_path, registration(tmp_path)), env=env) == 2


def test_plan_needs_a_principal_for_each_identity(tmp_path: Path) -> None:
    mod = load()
    args = plan_args(tmp_path, registration(tmp_path))
    i = args.index("--api-principal-id")
    del args[i : i + 2]
    assert mod.main(args, env={}) == 2


def test_foundry_hub_account_is_never_a_default(tmp_path: Path) -> None:
    mod = load()
    args = [
        "access-plan",
        "--registration",
        str(registration(tmp_path)),
        "--plan-file",
        str(tmp_path / "plan.json"),
    ]
    assert mod.main(args, env={}) == 2  # no resource named: refused, nothing assumed
    assert "aifndry" not in SCRIPT.read_text(encoding="utf-8").lower()
