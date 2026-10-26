"""PRP-32 item 4: deploy / grant / entra / seed / smoke flows of scripts/gates/hosted_demo.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
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


def _smoke_transport(readyz_status: int = 404) -> httpx.MockTransport:
    config = {
        "cloud": "AzureCloud",
        "tenantId": F.TENANT,
        "clientId": F.APP_ID,
        "apiBaseUrl": "/",
        "apiScope": "api://x/access",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "nsdemo-api.azurewebsites.net":
            raise httpx.ConnectError("private", request=request)
        if path == "/":
            return httpx.Response(200, text="<html></html>")
        if path == "/config.json":
            return httpx.Response(200, json=config, headers={"cache-control": "no-store"})
        if path == "/api/v1/me/domains":
            return httpx.Response(401)
        if path == "/readyz":
            return httpx.Response(readyz_status)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _smoke(env: Any, transport: httpx.MockTransport) -> int:
    argv = ["smoke", *env.common()]
    return env.mod.main(
        argv,
        runner=env.fake,
        work_dir=env.tmp / "work",
        backend_factory=lambda endpoint, database: env.backend,
        smoke_transport=transport,
    )


def test_smoke_runs_the_smoke_module_and_maps_pass_to_exit_0(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.calls.clear()
    assert _smoke(env, _smoke_transport()) == 0
    ev = env.evidence("smoke")
    assert ev["result"] == "PASS"
    assert ev["details"]["smoke"]["ok"] is True
    names = {c["name"] for c in ev["details"]["smoke"]["checks"]}
    assert {"frontend-root", "frontend-config-json", "api-host-refuses-direct"} <= names
    assert {"site-running:nsdemo-web", "site-health:nsdemo-workers"} <= names
    assert env.fake.count("monitor", "metrics", "list") == 3
    webapp_shows = [c for c in env.fake.calls if c[:2] == ["webapp", "show"]]
    assert {c[c.index("-n") + 1] for c in webapp_shows} == {
        "nsdemo-web", "nsdemo-api", "nsdemo-workers",
    }  # fmt: skip
    assert all(c[c.index("-g") + 1] == F.RG for c in webapp_shows)


def test_smoke_failure_is_exit_1_and_names_the_failed_check(env: Any) -> None:
    assert env.deploy() == 0
    assert _smoke(env, _smoke_transport(readyz_status=200)) == 1
    ev = env.evidence("smoke")
    assert ev["result"] == "FAIL"
    assert any("readyz-not-proxied" in e for e in ev["errors"])
    failed = [c for c in ev["details"]["smoke"]["checks"] if not c["passed"]]
    assert [c["name"] for c in failed] == ["readyz-not-proxied"]


def test_smoke_evidence_goes_through_the_scrubber(env: Any) -> None:
    assert env.deploy() == 0
    assert _smoke(env, _smoke_transport()) == 0
    text = next((env.tmp / "ev").glob("*-smoke.json")).read_text(encoding="utf-8")
    assert F.TENANT not in text and F.APP_ID not in text
    assert not env.mod.cm.GUID_RE.search(text)


# --------------------------------------------------------------------------- ownership


def test_pre_existing_group_and_resources_are_not_registered_as_created(env: Any) -> None:
    foreign = {"id": F._rid("Microsoft.Storage/storageAccounts", "theirs"), "type": "x/y"}
    env.fake.group_exists = True
    env.fake.rg_tags = {"owner": "someone-else"}
    env.fake.live = [foreign]
    assert env.deploy() == 0
    assert env.fake.index("group", "create") == -1
    rows = json.loads(
        (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )["rows"]
    by_id = {r["resource_id"].lower(): r for r in rows}
    assert by_id[foreign["id"].lower()]["ownership"] == "reused"
    assert by_id[f"/subscriptions/{F.SUB}/resourcegroups/{F.RG}"]["ownership"] == "reused"
    assert all(by_id[r["id"].lower()]["ownership"] == "created" for r in F.RESOURCES)
    assert env.evidence("deploy")["details"]["register_not_ours_count"] == 2


def test_snapshot_is_taken_before_the_deployment_is_created(env: Any) -> None:
    assert env.deploy() == 0
    assert 0 <= env.fake.index("resource", "list") < env.fake.index("deployment", "group", "create")


def test_a_new_resource_outside_the_approved_changes_is_not_ours(env: Any) -> None:
    sneaky = {"id": F._rid("Microsoft.Storage/storageAccounts", "sneaky"), "type": "x/y"}
    env.fake.appear_on_deploy = [sneaky]
    assert env.deploy() == 0
    rows = json.loads(
        (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )["rows"]
    by_id = {r["resource_id"].lower(): r for r in rows}
    assert by_id[sneaky["id"].lower()]["ownership"] == "reused"


# --------------------------------------------------------------------------- blank assignment id


def test_grant_model_access_fails_loudly_on_a_blank_assignment_id(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.blank_assignment_id = True
    rc = env.run(
        "grant-model-access", "--foundry-account-id", F.FOUNDRY,
        "--approve-shared", "foundry-role", infra=False,
    )  # fmt: skip
    assert rc == 1
    rows = json.loads(
        (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )["rows"]
    assert all(r["resource_id"].startswith("/") for r in rows)
    assert not any(r["service"] == "foundry-role" for r in rows)
    assert env.evidence("grant-model-access")["result"] == "FAIL"


def test_seed_access_fails_loudly_on_a_blank_assignment_id(env: Any) -> None:
    assert env.deploy() == 0
    env.fake.blank_assignment_id = True
    assert _seed(env, "--grant") == 1
    rows = json.loads(
        (env.tmp / "state" / "register-hosted-rg-ns-demo-test.json").read_text(encoding="utf-8")
    )["rows"]
    assert all(r["resource_id"].startswith("/") for r in rows)
    assert not any(r["service"] == "seed-access" for r in rows)
