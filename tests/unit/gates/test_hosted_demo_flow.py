"""PRP-32 item 4: deploy / grant / entra / seed / smoke flows of scripts/gates/hosted_demo.py."""

from __future__ import annotations

import importlib.util
import json
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


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.fixture
def env(tmp_path: Path) -> Any:
    return F.Env(tmp_path)


def test_deploy_runs_what_if_before_create_and_keeps_the_environment(env: Any) -> None:
    assert env.deploy("--keep") == 0
    assert env.fake.index("deployment", "group", "what-if") < env.fake.index(
        "deployment", "group", "create"
    )
    removers = [
        c for c in env.fake.calls if c[-1:] == ["--yes"] or "delete" in c[:4] or "remove" in c[:4]
    ]
    assert removers == []


def test_deploy_default_also_keeps(env: Any) -> None:
    assert env.deploy() == 0
    assert env.fake.index("group", "delete") == -1


def test_approvals_land_in_evidence_with_operator_and_utc(env: Any) -> None:
    assert env.deploy() == 0
    ev = env.evidence("deploy")
    tokens = {a["token"] for a in ev["approvals"]}
    assert {"hub-subnet", "hub-pe", "hub-dns", "budget", "plan-hash"} <= tokens
    for a in ev["approvals"]:
        assert a["operator"] == "frank"
        assert a["utc"].endswith("Z") and len(a["utc"]) == 20


def test_deploy_writes_both_register_copies_and_registration(env: Any) -> None:
    assert env.deploy() == 0
    state = env.tmp / "state"
    reg_file = state / "register-hosted-rg-ns-demo-test.json"
    exported = json.loads(reg_file.read_text(encoding="utf-8"))
    ids = {r["resource_id"].lower() for r in exported["rows"]}
    assert all(r["id"].lower() in ids for r in F.RESOURCES)
    assert F.BUDGET_ID.lower() in ids
    shared = [r for r in exported["rows"] if r["ownership"] == "shared"]
    assert {r["consent_reference"] for r in shared} >= {
        "approve-shared:hub-subnet",
        "approve-shared:hub-pe",
        "approve-shared:hub-dns",
    }
    assert len(env.backend.rows) == len(exported["rows"])
    registration = json.loads((state / "registration.json").read_text(encoding="utf-8"))
    assert set(registration) == {
        "schema", "deployment_id", "cloud", "cosmos_host", "eventhubs_host", "blob_host",
        "key_vault_host", "database", "event_hub", "archive_container",
        "pseudonym_secret_uri", "workers_object_id", "customer_id",
    }  # fmt: skip
    assert registration["cosmos_host"] == "nsdemocosmos.documents.azure.com"
    assert registration["eventhubs_host"] == "nsdemo-ehns.servicebus.windows.net"
    assert registration["pseudonym_secret_uri"].endswith("/secrets/pseudonym-key")
    assert "://" not in registration["blob_host"]


def test_cosmos_register_failure_is_reported_not_hidden(env: Any) -> None:
    def boom(rows: Any) -> None:
        raise RuntimeError("no route")

    env.backend.put_rows = boom
    assert env.deploy() == 1
    assert (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").exists()


@pytest.mark.parametrize(
    ("site", "field", "value"),
    [
        ("nsdemo-web", "publicNetworkAccess", "Disabled"),
        ("nsdemo-api", "publicNetworkAccess", "Enabled"),
        ("nsdemo-workers", "publicNetworkAccess", "Enabled"),
        ("nsdemo-api", "linuxFxVersion", "DOCKER|ghcr.io/other/api:1"),
    ],
)
def test_post_check_fails_loudly_on_policy_modified_sites(
    env: Any, site: str, field: str, value: str
) -> None:
    env.fake.sites[site][field] = value
    assert env.deploy() == 1
    assert env.evidence("deploy")["result"] == "FAIL"


# --------------------------------------------------------------------------- D4 secret


def test_pseudonym_secret_is_created_once_without_leaking(
    env: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert env.deploy() == 0
    value = env.fake.secret_seen
    assert len(value) >= 48
    set_call = next(c for c in env.fake.calls if c[:3] == ["keyvault", "secret", "set"])
    assert "--file" in set_call and "--value" not in set_call
    assert all(value not in arg for call in env.fake.calls for arg in call)
    out = capsys.readouterr()
    assert value not in out.out and value not in out.err
    for path in (env.tmp / "ev").iterdir():
        assert value not in path.read_text(encoding="utf-8")
    assert all(not Path(p).exists() for p in env.fake.kv_set_files)
    assert env.fake.index("keyvault", "secret", "show") == -1


def test_pseudonym_temp_file_removed_even_when_set_fails(env: Any) -> None:
    env.fake.kv_set_rc = 1
    assert env.deploy() == 1
    assert env.fake.kv_set_files
    assert all(not Path(p).exists() for p in env.fake.kv_set_files)
    assert list((env.tmp / "work").glob("kv-*")) == []


def test_existing_pseudonym_secret_is_never_overwritten(env: Any) -> None:
    env.fake.kv_names = ["pseudonym-key"]
    assert env.deploy() == 0
    assert env.fake.index("keyvault", "secret", "set") == -1
    assert env.fake.index("keyvault", "secret", "show") == -1


# --------------------------------------------------------------------------- shared steps


def test_grant_model_access_assigns_openai_user_without_keys(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.calls.clear()
    rc = env.run(
        "grant-model-access", "--foundry-account-id", F.FOUNDRY,
        "--approve-shared", "foundry-role", infra=False,
    )  # fmt: skip
    assert rc == 0
    create = next(c for c in env.fake.calls if c[:3] == ["role", "assignment", "create"])
    assert "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" in create
    assert create[create.index("--assignee-object-id") + 1] == F.OID_API
    assert create[create.index("--scope") + 1] == F.FOUNDRY
    flat = " ".join(" ".join(c) for c in env.fake.calls).lower()
    assert "listkeys" not in flat and "list-keys" not in flat
    ev = env.evidence("grant-model-access")
    assert [a["token"] for a in ev["approvals"]] == ["foundry-role"]
    rows = json.loads(
        (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )["rows"]
    by_service = {
        r["service"]: r for r in rows if r["service"] in ("foundry-role", "foundry-account")
    }
    assert by_service["foundry-role"]["ownership"] == "created"
    assert by_service["foundry-account"]["ownership"] == "shared"


def test_entra_redirect_merges_and_saves_prior_list(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.calls.clear()
    rc = env.run(
        "entra-redirect", "--entra-client-id", F.APP_ID, "--approve-shared", "entra-app",
        infra=False,
    )  # fmt: skip
    assert rc == 0
    assert env.fake.patches == [
        {
            "spa": {
                "redirectUris": ["http://localhost:5173", "https://nsdemo-web.azurewebsites.net/"]
            }
        }
    ]
    saved = json.loads(
        (env.tmp / "state" / "entra-prior-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )
    assert saved["prior_spa_redirect_uris"] == ["http://localhost:5173"]
    patch = next(c for c in env.fake.calls if c[:1] == ["rest"] and "patch" in c)
    assert patch[patch.index("--body") + 1].startswith("@")
    assert list((env.tmp / "work").glob("entra-*")) == []
    assert [a["token"] for a in env.evidence("entra-redirect")["approvals"]] == ["entra-app"]


def test_entra_redirect_is_idempotent(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.app_spa = ["https://nsdemo-web.azurewebsites.net/"]
    env.fake.calls.clear()
    rc = env.run(
        "entra-redirect", "--entra-client-id", F.APP_ID, "--approve-shared", "entra-app",
        infra=False,
    )  # fmt: skip
    assert rc == 0 and env.fake.patches == []


def _seed(env: Any, flag: str) -> int:
    return env.run("seed-access", flag, "--principal", F.OID_OPERATOR, infra=False)


def test_seed_access_grants_four_scoped_roles_and_revokes_them(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.calls.clear()
    assert _seed(env, "--grant") == 0
    assert env.fake.count("cosmosdb", "sql", "role", "assignment", "create") == 1
    cosmos = next(
        c for c in env.fake.calls if c[:5] == ["cosmosdb", "sql", "role", "assignment", "create"]
    )
    assert (
        cosmos[cosmos.index("--role-definition-id") + 1] == "00000000-0000-0000-0000-000000000002"
    )
    assert cosmos[cosmos.index("--scope") + 1] == "/dbs/neurosphere"
    scopes = [
        c[c.index("--scope") + 1]
        for c in env.fake.calls
        if c[:3] == ["role", "assignment", "create"]
    ]
    assert len(scopes) == 3
    assert any(s.endswith("/eventhubs/telemetry") for s in scopes)
    assert any(s.endswith("/containers/archive") for s in scopes)
    assert any(s.endswith("/secrets/pseudonym-key") for s in scopes)
    assert env.evidence("seed-access")["details"]["expires_hint_hours"] == 8

    env.fake.calls.clear()
    assert _seed(env, "--revoke") == 0
    assert env.fake.count("cosmosdb", "sql", "role", "assignment", "delete") == 1


def test_seed_access_refuses_without_a_readable_register(env: Any) -> None:
    assert _seed(env, "--grant") == 2
    assert env.fake.index("role", "assignment", "create") == -1


# --------------------------------------------------------------------------- smoke wiring


def test_smoke_delegates_to_the_smoke_module(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    fake_mod = ModuleType("_hosted_demo_smoke")

    def run_smoke(**kwargs: Any) -> int:
        seen.update(kwargs)
        return 0

    fake_mod.run_smoke = run_smoke  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_hosted_demo_smoke", fake_mod)
    assert env.run("smoke", infra=False) == 0
    assert seen["frontend_host"] == "nsdemo-web.azurewebsites.net"
    assert seen["resource_group"] == F.RG


def test_smoke_failure_is_exit_1(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = ModuleType("_hosted_demo_smoke")
    fake_mod.run_smoke = lambda **_: 1  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_hosted_demo_smoke", fake_mod)
    assert env.run("smoke", infra=False) == 1
