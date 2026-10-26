"""PRP-32 item 4: refusals of scripts/gates/hosted_demo.py, plus the shared fake `az` runner.

The other two hosted_demo test files load this module by path for ``FakeAz`` and the helpers.
Every test drives the script through a fake runner: no subprocess `az`, no network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

import pytest

GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
SCRIPT = GATES / "hosted_demo.py"
TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "demo" / "main.bicep"
SUB = "11111111-2222-3333-4444-555555555555"
RG = "rg-ns-demo-test"
BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
HUB = f"/subscriptions/{SUB}/resourceGroups/rg-hub/providers/Microsoft.Network"
INTEG_SUBNET = f"{HUB}/virtualNetworks/vnet-hub/subnets/snet-functions"
PE_SUBNET = f"{HUB}/virtualNetworks/vnet-hub/subnets/snet-private-endpoints"
ZONES = {
    "cosmos": "privatelink.documents.azure.com",
    "eventhubs": "privatelink.servicebus.windows.net",
    "blob": "privatelink.blob.core.windows.net",
    "webapps": "privatelink.azurewebsites.net",
    "keyvault": "privatelink.vaultcore.azure.net",
}
ZONE_IDS = {k: f"{HUB}/privateDnsZones/{v}" for k, v in ZONES.items()}
FOUNDRY = (
    f"/subscriptions/{SUB}/resourceGroups/rg-hub/providers"
    "/Microsoft.CognitiveServices/accounts/aif-test"
)
OID_API = "aaaaaaaa-0000-0000-0000-000000000001"
OID_WORKERS = "aaaaaaaa-0000-0000-0000-000000000002"
OID_OPERATOR = "aaaaaaaa-0000-0000-0000-000000000003"
APP_ID = "bbbbbbbb-0000-0000-0000-000000000001"
APP_OBJECT = "bbbbbbbb-0000-0000-0000-000000000002"
TENANT = "cccccccc-0000-0000-0000-000000000001"
FAKE_JWT = "eyJ" + "hbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
FAKE_KEY = "Account" + "Key=" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVm=="

OUTPUTS: dict[str, Any] = {
    "apiSiteName": "nsdemo-api",
    "workersSiteName": "nsdemo-workers",
    "frontendSiteName": "nsdemo-web",
    "frontendHostName": "nsdemo-web.azurewebsites.net",
    "apiHostName": "nsdemo-api.azurewebsites.net",
    "apiPrincipalId": OID_API,
    "workersPrincipalId": OID_WORKERS,
    "cosmosAccountName": "nsdemocosmos",
    "cosmosEndpoint": "https://nsdemocosmos.documents.azure.com:443/",
    "cosmosDatabaseName": "neurosphere",
    "eventHubsNamespaceName": "nsdemo-ehns",
    "eventHubsFqdn": "nsdemo-ehns.servicebus.windows.net",
    "eventHubName": "telemetry",
    "storageAccountName": "nsdemostore",
    "archiveContainerName": "archive",
    "keyVaultName": "nsdemo-kv",
    "pseudonymSecretName": "pseudonym-key",
    "privateEndpointIds": [],
}


def _rid(rtype: str, name: str) -> str:
    return f"{BASE}/{rtype}/{name}"


RESOURCES: list[dict[str, str]] = [
    {"id": _rid("Microsoft.Web/serverFarms", "nsdemo-plan"), "type": "Microsoft.Web/serverFarms"},
    {"id": _rid("Microsoft.Web/sites", "nsdemo-web"), "type": "Microsoft.Web/sites"},
    {"id": _rid("Microsoft.Web/sites", "nsdemo-api"), "type": "Microsoft.Web/sites"},
    {"id": _rid("Microsoft.Web/sites", "nsdemo-workers"), "type": "Microsoft.Web/sites"},
    {
        "id": _rid("Microsoft.Network/privateEndpoints", "nsdemo-cosmos-pe"),
        "type": "Microsoft.Network/privateEndpoints",
    },
    {
        "id": _rid("Microsoft.Network/privateEndpoints", "nsdemo-api-pe"),
        "type": "Microsoft.Network/privateEndpoints",
    },
    {
        "id": _rid("Microsoft.Network/networkInterfaces", "nsdemo-api-pe-nic"),
        "type": "Microsoft.Network/networkInterfaces",
    },
    {
        "id": _rid("Microsoft.DocumentDB/databaseAccounts", "nsdemocosmos"),
        "type": "Microsoft.DocumentDB/databaseAccounts",
    },
    {
        "id": _rid("Microsoft.EventHub/namespaces", "nsdemo-ehns"),
        "type": "Microsoft.EventHub/namespaces",
    },
    {
        "id": _rid("Microsoft.Storage/storageAccounts", "nsdemostore"),
        "type": "Microsoft.Storage/storageAccounts",
    },
    {"id": _rid("Microsoft.KeyVault/vaults", "nsdemo-kv"), "type": "Microsoft.KeyVault/vaults"},
]
BUDGET_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Consumption/budgets/b1"


class R(NamedTuple):
    rc: int
    stdout: str
    stderr: str


def load_script() -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location("hosted_demo_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hosted_demo_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _opt(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1] if flag in args else ""


class FakeAz:
    """Canned `az` responses keyed on the leading arguments; records every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.cloud = "AzureCloud"
        self.account = SUB
        self.group_exists: Any = True
        self.changes: list[dict[str, Any]] = [
            {"changeType": "Create", "resourceId": r["id"]} for r in RESOURCES
        ]
        self.deploy_state = "Succeeded"
        self.live: list[dict[str, str]] = [dict(r) for r in RESOURCES]
        self.kv_names: list[str] = []
        self.kv_set_rc = 0
        self.kv_set_files: list[str] = []
        self.secret_seen = ""
        self.sites: dict[str, dict[str, str]] = {
            "nsdemo-web": self._site("Enabled", "frontend"),
            "nsdemo-api": self._site("Disabled", "api"),
            "nsdemo-workers": self._site("Disabled", "workers"),
        }
        self.app_spa: list[str] = ["http://localhost:5173"]
        self.patches: list[dict[str, Any]] = []
        self.role_present = False
        self.subnet: dict[str, Any] = {
            "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}],
            "serviceAssociationLinks": [],
            "ipConfigurations": [],
            "routeTable": None,
            "defaultOutboundAccess": None,
            "networkSecurityGroup": {"id": f"{HUB}/networkSecurityGroups/nsg1"},
        }
        self.nsg: dict[str, Any] = {"securityRules": []}
        self.foundry_deployments = ["mini"]
        self.params_seen: dict[str, Any] = {}
        self.cosmos_assignments: list[dict[str, str]] = []

    @staticmethod
    def _site(public: str, image: str) -> dict[str, str]:
        return {
            "publicNetworkAccess": public,
            "linuxFxVersion": f"DOCKER|ghcr.io/fgarofalo56/neurosphere/{image}:0.1.0-rc.2",
        }

    def verbs(self) -> list[str]:
        return [" ".join(c[:3]) for c in self.calls]

    def index(self, *prefix: str) -> int:
        n = len(prefix)
        for i, c in enumerate(self.calls):
            if c[:n] == list(prefix):
                return i
        return -1

    def count(self, *prefix: str) -> int:
        n = len(prefix)
        return sum(1 for c in self.calls if c[:n] == list(prefix))

    def __call__(self, args: Sequence[str]) -> R:
        a = list(args)
        self.calls.append(a)
        ok = lambda body="": R(0, json.dumps(body) if body != "" else "", "")  # noqa: E731
        h2, h3 = " ".join(a[:2]), " ".join(a[:3])
        if h2 == "cloud show":
            return ok(self.cloud)
        if h2 == "account show":
            return ok(self.account)
        if h2 == "group exists":
            return ok(self.group_exists)
        if h2 in ("group create", "group delete"):
            return ok({})
        if h2 == "group show":
            return ok({"delete-after": "2026-11-25", "owner": "x"})
        if h3 == "deployment group what-if":
            path = _opt(a, "--parameters").lstrip("@")
            try:
                self.params_seen = json.loads(Path(path).read_text(encoding="utf-8"))
            except OSError:
                self.params_seen = {}
            return ok({"changes": self.changes})
        if h3 == "deployment group create":
            outs = {k: {"type": "String", "value": v} for k, v in OUTPUTS.items()}
            body = {"properties": {"provisioningState": self.deploy_state, "outputs": outs}}
            return ok(body)
        if h3 == "deployment group show":
            return ok({k: {"type": "String", "value": v} for k, v in OUTPUTS.items()})
        if h2 == "resource list":
            return ok(self.live)
        if h2 == "provider show":
            return ok("Registered")
        if h3 == "network vnet subnet":
            return ok(self.subnet if _opt(a, "--ids") == INTEG_SUBNET else {})
        if h3 == "network nsg show":
            return ok(self.nsg)
        if h3 == "network private-dns zone":
            return ok({})
        if h2 == "cognitiveservices account":
            return ok(self.foundry_deployments)
        if h3 == "keyvault secret list":
            return ok(self.kv_names)
        if h3 == "keyvault secret set":
            path = _opt(a, "--file")
            self.kv_set_files.append(path)
            self.secret_seen = Path(path).read_text(encoding="utf-8")
            return R(self.kv_set_rc, "", "Forbidden" if self.kv_set_rc else "")
        if h2 == "webapp show":
            return ok(self.sites[_opt(a, "--name")])
        if a[0] == "rest":
            return self._rest(a)
        if h3 == "role assignment list":
            return ok(["/x/existing"] if self.role_present else [])
        if h3 == "role assignment create":
            rid = f"{_opt(a, '--scope')}/providers/Microsoft.Authorization/roleAssignments/"
            return ok({"id": rid + "dddddddd-0000-0000-0000-" + str(len(self.calls)).zfill(12)})
        if h3 == "role assignment delete":
            return ok()
        if a[:5] == ["cosmosdb", "sql", "role", "assignment", "list"]:
            return ok(self.cosmos_assignments)
        if a[:5] == ["cosmosdb", "sql", "role", "assignment", "create"]:
            rid = (
                f"{BASE}/Microsoft.DocumentDB/databaseAccounts/nsdemocosmos/sqlRoleAssignments/"
                "eeeeeeee-0000-0000-0000-000000000001"
            )
            made = {
                "id": rid,
                "principalId": _opt(a, "--principal-id"),
                "roleDefinitionId": _opt(a, "--role-definition-id"),
                "scope": _opt(a, "--scope"),
            }
            self.cosmos_assignments.append(made)
            return ok(made)
        if a[:5] == ["cosmosdb", "sql", "role", "assignment", "delete"]:
            self.cosmos_assignments.clear()
            return ok()
        if h3 in ("webapp vnet-integration remove", "network private-endpoint delete"):
            return ok()
        if h2 in ("webapp delete", "resource delete", "keyvault delete"):
            return ok()
        if h3 == "appservice plan delete":
            return ok()
        return R(1, "", f"unexpected call {a}")

    def _rest(self, a: list[str]) -> R:
        method, url = _opt(a, "--method"), _opt(a, "--url")
        if method == "get" and "Consumption/budgets" in url:
            return R(0, json.dumps([BUDGET_ID]), "")
        if method == "get":
            return R(0, json.dumps({"id": APP_OBJECT, "spa": {"redirectUris": self.app_spa}}), "")
        if method == "patch":
            body = json.loads(Path(_opt(a, "--body").lstrip("@")).read_text(encoding="utf-8"))
            self.patches.append(body)
            self.app_spa = list(body["spa"]["redirectUris"])
            return R(0, "", "")
        return R(0, "", "")  # delete (budget)


class FakeBackend:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def put_rows(self, rows: Sequence[Any]) -> None:
        self.rows = list(rows)

    def list_rows(self, deployment_id: str) -> list[Any]:
        return [r for r in self.rows if r.deployment_id == deployment_id]


class Env:
    """One test's directories, fake runner and backend."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.fake = FakeAz()
        self.backend = FakeBackend()
        self.mod = load_script()

    def common(self) -> list[str]:
        return [
            "--subscription", SUB, "--resource-group", RG, "--operator", "frank",
            "--evidence-dir", str(self.tmp / "ev"), "--state-dir", str(self.tmp / "state"),
        ]  # fmt: skip

    def infra(self) -> list[str]:
        return [
            "--image-tag", "0.1.0-rc.2",
            "--integration-subnet-id", INTEG_SUBNET,
            "--private-endpoint-subnet-id", PE_SUBNET,
            "--cosmos-zone-id", ZONE_IDS["cosmos"],
            "--eventhubs-zone-id", ZONE_IDS["eventhubs"],
            "--blob-zone-id", ZONE_IDS["blob"],
            "--webapps-zone-id", ZONE_IDS["webapps"],
            "--keyvault-zone-id", ZONE_IDS["keyvault"],
            "--entra-tenant-id", TENANT,
            "--entra-client-id", APP_ID,
            "--copilot-endpoint", "https://aif-test.cognitiveservices.azure.com/",
            "--budget-contact-emails", "ops@example.invalid",
            "--tag-owner", "frank",
        ]  # fmt: skip

    def run(self, command: str, *extra: str, infra: bool = True) -> int:
        argv = [command, *self.common(), *(self.infra() if infra else []), *extra]
        return self.mod.main(
            argv,
            runner=self.fake,
            work_dir=self.tmp / "work",
            backend_factory=lambda endpoint, database: self.backend,
        )

    def plan_hash(self) -> str:
        assert self.run("plan") == 0
        data = json.loads(next((self.tmp / "ev").glob("*-plan.json")).read_text(encoding="utf-8"))
        return str(data["details"]["plan_sha256"])

    def deploy(self, *extra: str, shared: str = "hub-subnet,hub-pe,hub-dns,budget") -> int:
        digest = self.plan_hash()
        self.fake.calls.clear()
        return self.run("deploy", "--approve-plan", digest, "--approve-shared", shared, *extra)

    def evidence(self, command: str) -> dict[str, Any]:
        files = sorted((self.tmp / "ev").glob(f"*-{command}.json"))
        return json.loads(files[-1].read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# --------------------------------------------------------------------------- refusals


@pytest.mark.parametrize("value", [None, "0", "true", "", "yes"])
def test_refuses_without_approval_and_runs_nothing(
    value: str | None,
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if value is None:
        monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    else:
        monkeypatch.setenv("NS_LIVE_APPROVED", value)
    assert env.mod.main([], runner=env.fake, work_dir=env.tmp) == 2  # refusal precedes argparse
    assert "REFUSED" in capsys.readouterr().err
    assert env.fake.calls == []
    assert not (env.tmp / "ev").exists()


def test_subprocess_refuses_end_to_end() -> None:
    clean = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    zero = "00000000-0000-0000-0000-000000000000"
    command = [sys.executable, str(SCRIPT), "preflight", "--subscription", zero]
    proc = subprocess.run(
        command, env=clean, capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 2
    assert "REFUSED" in proc.stderr


def test_refuses_before_any_az_call_when_register_is_not_importable(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "neurosphere_core.deploy.register", None)
    assert env.run("plan") == 2
    assert "uv run" in capsys.readouterr().err
    assert env.fake.calls == []


@pytest.mark.parametrize("loc", ["usgovvirginia", "usdodeast", "USGovArizona"])
def test_refuses_government_region_with_zero_calls(env: Env, loc: str) -> None:
    assert env.run("plan", "--location", loc) == 2
    assert env.fake.calls == []


@pytest.mark.parametrize(
    ("cloud", "account"),
    [("AzureUSGovernment", SUB), ("AzureCloud", "99999999-0000-0000-0000-000000000000")],
)
@pytest.mark.parametrize("command", ["plan", "preflight", "status"])
def test_refuses_wrong_cloud_or_account_before_mutation(
    env: Env, cloud: str, account: str, command: str
) -> None:
    env.fake.cloud, env.fake.account = cloud, account
    extra = ["--foundry-account-id", FOUNDRY] if command == "preflight" else []
    assert env.run(command, *extra) == 2
    assert all(c[0] in ("cloud", "account") for c in env.fake.calls)


def test_never_calls_account_set(env: Env) -> None:
    assert env.deploy() == 0
    assert env.fake.index("account", "set") == -1


def test_operator_must_not_be_an_email(env: Env) -> None:
    argv = ["plan", *env.common(), *env.infra()]
    argv[argv.index("frank")] = "me@example.invalid"
    assert env.mod.main(argv, runner=env.fake, work_dir=env.tmp) == 2
    assert env.fake.calls == []


@pytest.mark.parametrize("missing", ["hub-subnet", "hub-pe", "hub-dns", "budget"])
def test_deploy_refuses_each_missing_shared_token(env: Env, missing: str) -> None:
    digest = env.plan_hash()
    env.fake.calls.clear()
    tokens = ",".join(t for t in ("hub-subnet", "hub-pe", "hub-dns", "budget") if t != missing)
    assert env.run("deploy", "--approve-plan", digest, "--approve-shared", tokens) == 2
    assert env.fake.index("deployment", "group", "create") == -1
    assert env.fake.index("group", "create") == -1


def test_deploy_refuses_unknown_shared_token(env: Env) -> None:
    assert env.run("deploy", "--approve-plan", "x", "--approve-shared", "everything") == 2
    assert env.fake.index("deployment", "group", "create") == -1


def test_deploy_without_plan_hash_refuses_after_what_if_with_no_create(env: Env) -> None:
    rc = env.run("deploy", "--approve-shared", "hub-subnet,hub-pe,hub-dns,budget")
    assert rc == 2
    assert env.fake.index("deployment", "group", "what-if") != -1
    assert env.fake.index("deployment", "group", "create") == -1


def test_deploy_with_stale_plan_hash_refuses_after_what_if_with_no_create(env: Env) -> None:
    digest = env.plan_hash()
    env.fake.changes.append({"changeType": "Create", "resourceId": _rid("Microsoft.X/y", "new")})
    env.fake.calls.clear()
    rc = env.run(
        "deploy", "--approve-plan", digest, "--approve-shared", "hub-subnet,hub-pe,hub-dns,budget"
    )
    assert rc == 2
    assert env.fake.index("deployment", "group", "what-if") != -1
    assert env.fake.index("deployment", "group", "create") == -1


def test_deploy_never_creates_the_resource_group(env: Env) -> None:
    env.fake.group_exists = False
    rc = env.run(
        "deploy", "--approve-plan", "x", "--approve-shared", "hub-subnet,hub-pe,hub-dns,budget"
    )
    assert rc == 2
    assert env.fake.index("group", "create") == -1


def test_grant_model_access_refuses_without_token(env: Env) -> None:
    rc = env.run("grant-model-access", "--foundry-account-id", FOUNDRY, infra=False)
    assert rc == 2
    assert env.fake.index("role", "assignment", "create") == -1


def test_entra_redirect_refuses_without_token(env: Env) -> None:
    assert env.run("entra-redirect", "--entra-client-id", APP_ID, infra=False) == 2
    assert env.fake.index("rest") == -1


def test_smoke_exits_2_when_the_smoke_module_is_absent(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "_hosted_demo_smoke", None)
    assert env.run("smoke", infra=False) == 2
    assert "not available" in capsys.readouterr().err
    assert env.fake.calls == []


# --------------------------------------------------------------------------- scrubber


def test_scrubber_fails_on_fake_key_and_jwt(env: Env) -> None:
    g01 = env.mod.cm.g01()
    for bad in (FAKE_JWT, FAKE_KEY, "-----BEGIN" + " PRIVATE KEY-----"):
        with pytest.raises(g01.ScrubError):
            env.mod.cm.finalize_evidence({"steps": [{"detail": bad}]}, SUB)
    with pytest.raises(g01.ScrubError):
        env.mod.cm.finalize_evidence({"primaryKey": "x"}, SUB)


def test_run_with_secret_shaped_data_withholds_evidence_and_fails(env: Env) -> None:
    env.fake.changes = [{"changeType": "Create", "resourceId": _rid("Microsoft.X/y", FAKE_KEY)}]
    assert env.run("plan") == 1
    text = next((env.tmp / "ev").glob("*-plan.json")).read_text(encoding="utf-8")
    assert "QUJDREVG" not in text
    assert json.loads(text)["result"] == "FAIL"


def test_guids_are_redacted_in_written_evidence(env: Env) -> None:
    assert env.run("plan") == 0
    for path in (env.tmp / "ev").iterdir():
        text = path.read_text(encoding="utf-8")
        assert SUB not in text
        assert TENANT not in text
        assert APP_ID not in text
        assert not env.mod.cm.GUID_RE.search(text)


# --------------------------------------------------------------------------- param contract


def _template_params() -> dict[str, bool]:
    text = TEMPLATE.read_text(encoding="utf-8")
    found: dict[str, bool] = {}
    for m in re.finditer(r"^param\s+(\w+)\s+[^\n=]+?(=)?\s*(?:[^\n]*)$", text, re.MULTILINE):
        found[m.group(1)] = m.group(2) is not None
    return found


def test_generated_params_match_the_declared_contract(env: Env) -> None:
    assert env.run("plan") == 0
    assert set(env.fake.params_seen["parameters"]) == set(env.mod.cm.GENERATED_PARAMS)
    assert env.fake.params_seen["parameters"]["deployKeyVault"]["value"] is True
    assert env.fake.params_seen["parameters"]["budgetContactEmails"]["value"] == [
        "ops@example.invalid"
    ]


@pytest.mark.skipif(not TEMPLATE.exists(), reason="infra/demo/main.bicep not landed yet (item 3)")
def test_generated_params_match_main_bicep() -> None:
    declared = _template_params()
    generated = set(load_script().cm.GENERATED_PARAMS)
    assert generated <= set(declared), sorted(generated - set(declared))
    assert {n for n, has_default in declared.items() if not has_default} <= generated


# --------------------------------------------------------------------------- plan / preflight


def test_plan_creates_tagged_group_when_absent_and_prints_hash(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.fake.group_exists = False
    assert env.run("plan") == 0
    create = next(c for c in env.fake.calls if c[:2] == ["group", "create"])
    tags = create[create.index("--tags") + 1 : create.index("--output")]
    keys = {t.split("=", 1)[0] for t in tags}
    assert keys == {
        "owner", "project", "env", "delete-after", "neurosphere:created-by",
        "neurosphere:deployment-id",
    }  # fmt: skip
    assert "project=neurosphere" in tags and "env=demo" in tags
    assert re.search(r"PLAN SHA256: [0-9a-f]{64}", capsys.readouterr().out)
    assert env.fake.index("deployment", "group", "create") == -1


def test_plan_hash_is_stable_and_order_independent(env: Env) -> None:
    first = env.plan_hash()
    env.fake.changes.reverse()
    for f in (env.tmp / "ev").iterdir():
        f.unlink()
    assert env.plan_hash() == first


def test_preflight_passes_with_a_clean_hub(env: Env) -> None:
    assert env.run("preflight", "--foundry-account-id", FOUNDRY) == 0
    mutating = [c for c in env.fake.calls if c[:2] in (["group", "create"], ["role", "assignment"])]
    assert mutating == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.subnet.update(routeTable={"id": "rt"}),
        lambda f: f.subnet.update(defaultOutboundAccess=False),
        lambda f: f.subnet.update(serviceAssociationLinks=[{"id": "l"}]),
        lambda f: f.subnet.update(ipConfigurations=[{"id": "i"}]),
        lambda f: f.subnet.update(delegations=[]),
        lambda f: f.nsg.update(
            securityRules=[
                {"direction": "Outbound", "access": "Deny", "destinationAddressPrefix": "Internet"}
            ]
        ),
        lambda f: setattr(f, "foundry_deployments", ["other"]),
    ],
)
def test_preflight_fails_on_each_hub_problem(env: Env, mutate: Any) -> None:
    mutate(env.fake)
    assert env.run("preflight", "--foundry-account-id", FOUNDRY) == 1


def test_preflight_fails_when_a_zone_id_is_the_wrong_zone(env: Env) -> None:
    env.fake.calls.clear()
    argv = ["preflight", *env.common(), *env.infra(), "--foundry-account-id", FOUNDRY]
    i = argv.index("--keyvault-zone-id")
    argv[i + 1] = f"{HUB}/privateDnsZones/privatelink.example.invalid"
    assert env.mod.main(argv, runner=env.fake, work_dir=env.tmp / "w") == 1


def test_status_reports_drift_and_delete_after(env: Env) -> None:
    env.fake.changes = [{"changeType": "Modify", "resourceId": RESOURCES[0]["id"]}]
    assert env.run("status") == 0
    details = env.evidence("status")["details"]
    assert details["drift_count"] == 1
    assert details["delete_after"] == "2026-11-25"
