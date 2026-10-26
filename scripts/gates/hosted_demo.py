"""PRP-32 item 4: gated deploy / operate / teardown script for the persistent hosted demo.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1, checked first, before argument
parsing, any project import or any `az` call. Run it with `uv run python` so that
``neurosphere_core`` imports (the register is needed for teardown). Agents never run it; the
operator does, after `az account set --subscription <name>` (this script never calls it).

    preflight | plan | deploy | grant-model-access | entra-redirect | seed-access | smoke
    | teardown | status

Safety contract:

* Commercial only: `az cloud show` must be AzureCloud, `az account show` must equal
  ``--subscription``, Government regions are refused.
* ``plan`` runs `what-if` and prints the sha256 of the normalized change list. ``deploy`` needs
  ``--approve-plan <hash>`` and ``--approve-shared hub-subnet,hub-pe,hub-dns,budget``; it re-runs
  what-if and refuses before any create when the hash changed.
* ``grant-model-access`` needs ``foundry-role``; ``entra-redirect`` needs ``entra-app``. Every
  approval is recorded in the evidence with ``--operator`` and the UTC time.
* The environment is persistent: only ``teardown --confirm <deployment-id>`` removes anything,
  and only rows the ownership register records as created by NeuroSphere. Shared resources
  (hub subnet, DNS zones, Foundry account, Entra app object) are never deleted.
* Nothing here reads secrets: no `listKeys`, no `keyvault secret show`. The pseudonym key
  (D4) is generated locally, handed to Key Vault with `--file`, and never appears in argv,
  logs, evidence or output.

Parameters generated for ``infra/demo/main.bicep`` (D9; a test compares them to the template):
prefix, location, imageRegistry, imageTag, appServiceSkuName, deployKeyVault,
integrationSubnetId, privateEndpointSubnetId, cosmosDnsZoneId, eventHubsDnsZoneId, blobDnsZoneId,
webAppsDnsZoneId, keyVaultDnsZoneId, entraTenantId, entraClientId, copilotEndpoint,
copilotDeployment, budgetAmount, budgetStartDate, budgetContactEmails, tagOwner, tagDeleteAfter,
deploymentId, createdBy.

Exit codes: 0 ok, 1 failed (evidence written), 2 refused (nothing changed).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _hosted_demo_common as cm  # noqa: E402

AZ_TIMEOUT_SECONDS = 3 * 60 * 60
MUTATING = frozenset(
    {"plan", "deploy", "grant-model-access", "entra-redirect", "seed-access", "teardown"}
)
_GOV_PREFIXES = ("usgov", "usdod")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_NOT_FOUND = ("notfound", "not found", "could not be found", "does not exist", "was not found")
_ARM_API = "https://management.azure.com"
_BUDGET_API = "2023-05-01"
_GRAPH = "https://graph.microsoft.com/v1.0"
_PROVIDERS = (
    "Microsoft.Web",
    "Microsoft.DocumentDB",
    "Microsoft.EventHub",
    "Microsoft.Storage",
    "Microsoft.KeyVault",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights",
    "Microsoft.Consumption",
)


class AzResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


AzRunner = Callable[[Sequence[str]], AzResult]


class AzError(RuntimeError):
    pass


class RefusedError(RuntimeError):
    """A precondition failed before anything was changed."""


class SubprocessAzRunner:
    """The real runner: list args, no shell. On Windows it calls the CLI's bundled Python so
    that Graph URLs with parentheses survive (see p29_entra_local.az_command)."""

    def __init__(self, az_path: str) -> None:
        self._prefix = cm.p29().az_command(az_path)

    def __call__(self, args: Sequence[str]) -> AzResult:
        proc = subprocess.run(
            [*self._prefix, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=AZ_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        return AzResult(proc.returncode, proc.stdout, proc.stderr)


class CosmosRegisterBackend:
    """Register copy in the hosted Cosmos ``deploy_register`` container (Entra data plane)."""

    def __init__(self, endpoint: str, database: str) -> None:
        self._endpoint = endpoint
        self._database = database

    def put_rows(self, rows: Sequence[Any]) -> None:
        asyncio.run(self._put(rows))

    def list_rows(self, deployment_id: str) -> list[Any]:
        return asyncio.run(self._list(deployment_id))

    async def _store(self) -> tuple[Any, Any, Any]:
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential
        from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore

        cred = DefaultAzureCredential()
        client = CosmosClient(self._endpoint, credential=cred)
        store = CosmosRegisterStore.from_client(
            client, database=self._database, container=cm.REGISTER_CONTAINER
        )
        return store, client, cred

    async def _put(self, rows: Sequence[Any]) -> None:
        store, client, cred = await self._store()
        try:
            for row in rows:
                await store.put_row(row)
        finally:
            await client.close()
            await cred.close()

    async def _list(self, deployment_id: str) -> list[Any]:
        store, client, cred = await self._store()
        try:
            return list(await store.list_rows(deployment_id))
        finally:
            await client.close()
            await cred.close()


BackendFactory = Callable[[str, str], Any]


def _default_backend(endpoint: str, database: str) -> Any:
    return CosmosRegisterBackend(endpoint, database)


# --------------------------------------------------------------------------- arguments

#: (flag, dest, default, help). Every one maps onto a D9 parameter of infra/demo/main.bicep.
INFRA_ARGS: tuple[tuple[str, str, str, str], ...] = (
    ("--prefix", "prefix", "nsdemo", "resource name prefix"),
    ("--image-registry", "image_registry", "ghcr.io/fgarofalo56/neurosphere", "image registry"),
    ("--image-tag", "image_tag", "", "pinned image tag (for example 0.1.0-rc.2)"),
    ("--sku", "sku", "B2", "App Service plan SKU"),
    ("--integration-subnet-id", "integration_subnet_id", "", "hub snet-functions ARM id"),
    ("--private-endpoint-subnet-id", "pe_subnet_id", "", "hub private-endpoint subnet ARM id"),
    ("--cosmos-zone-id", "cosmos_zone_id", "", "privatelink.documents.azure.com zone id"),
    ("--eventhubs-zone-id", "eventhubs_zone_id", "", "privatelink.servicebus.windows.net id"),
    ("--blob-zone-id", "blob_zone_id", "", "privatelink.blob.core.windows.net zone id"),
    ("--webapps-zone-id", "webapps_zone_id", "", "privatelink.azurewebsites.net zone id"),
    ("--keyvault-zone-id", "keyvault_zone_id", "", "privatelink.vaultcore.azure.net zone id"),
    ("--entra-tenant-id", "entra_tenant_id", "", "Entra tenant id"),
    ("--entra-client-id", "entra_client_id", "", "Entra API app (client) id"),
    ("--copilot-endpoint", "copilot_endpoint", "", "Foundry endpoint URL"),
    ("--copilot-deployment", "copilot_deployment", "mini", "Foundry deployment name"),
    ("--budget-amount", "budget_amount", "200", "monthly budget in USD"),
    ("--budget-start-date", "budget_start_date", "", "first of month, default this month"),
    ("--budget-contact-emails", "budget_emails", "", "comma-separated alert emails"),
    ("--tag-owner", "tag_owner", "", "value of the owner tag"),
    ("--tag-delete-after", "tag_delete_after", "", "delete-after date, default today+30d"),
    ("--created-by", "created_by", "neurosphere", "value of neurosphere:created-by"),
)
_DEPLOY_REQUIRED = (
    "image_tag",
    "integration_subnet_id",
    "pe_subnet_id",
    "cosmos_zone_id",
    "eventhubs_zone_id",
    "blob_zone_id",
    "webapps_zone_id",
    "entra_tenant_id",
    "entra_client_id",
    "copilot_endpoint",
    "budget_emails",
    "tag_owner",
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="PRP-32 hosted demo (operator-approved).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--subscription", required=True, help="Commercial subscription id")
    common.add_argument("--resource-group", default=cm.DEFAULT_RG)
    common.add_argument("--location", default=cm.DEFAULT_LOCATION)
    common.add_argument("--operator", default="", help="operator name recorded with approvals")
    common.add_argument("--deployment-id", default="", help="default: derived from the group")
    common.add_argument("--evidence-dir", default=str(cm.EVIDENCE_DIR))
    common.add_argument("--state-dir", default=str(cm.STATE_DIR), help="register/registration")
    sub = ap.add_subparsers(dest="command", required=True)

    def infra(p: argparse.ArgumentParser) -> None:
        for flag, dest, default, help_text in INFRA_ARGS:
            p.add_argument(flag, dest=dest, default=default, help=help_text)
        p.add_argument("--no-key-vault", action="store_true", help="deployKeyVault=false")

    p = sub.add_parser("preflight", parents=[common], help="read-only checks")
    infra(p)
    p.add_argument("--foundry-account-id", default="", help="Foundry account ARM id")
    p = sub.add_parser("plan", parents=[common], help="create the group, run what-if")
    infra(p)
    p = sub.add_parser("deploy", parents=[common], help="what-if again, then deploy")
    infra(p)
    p.add_argument("--approve-plan", default="", help="sha256 printed by `plan`")
    p.add_argument("--approve-shared", default="", help="comma list of shared-step tokens")
    p.add_argument("--keep", action="store_true", help="accepted; keeping is the default")
    p.add_argument("--customer-id", default="synthco")
    p = sub.add_parser("grant-model-access", parents=[common])
    p.add_argument("--foundry-account-id", required=True)
    p.add_argument("--approve-shared", default="")
    p = sub.add_parser("entra-redirect", parents=[common])
    p.add_argument("--entra-client-id", required=True)
    p.add_argument("--approve-shared", default="")
    p = sub.add_parser("seed-access", parents=[common])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--grant", action="store_true")
    mode.add_argument("--revoke", action="store_true")
    p.add_argument("--principal", required=True, help="operator object id")
    p.add_argument("--expires-hours", type=int, default=8, help="time-box hint for the evidence")
    sub.add_parser("smoke", parents=[common])
    p = sub.add_parser("teardown", parents=[common])
    p.add_argument("--confirm", default="", help="the deployment id")
    p = sub.add_parser("status", parents=[common], help="read-only drift and delete-after")
    infra(p)
    return ap


# --------------------------------------------------------------------------- context


@dataclass
class Ctx:
    run_az: AzRunner
    args: argparse.Namespace
    work_dir: Path
    backend_factory: BackendFactory
    steps: list[dict[str, Any]] = field(default_factory=lambda: [])
    approvals: list[dict[str, str]] = field(default_factory=lambda: [])
    errors: list[str] = field(default_factory=lambda: [])
    details: dict[str, Any] = field(default_factory=lambda: {})

    @property
    def sub(self) -> str:
        return str(self.args.subscription)

    @property
    def rg(self) -> str:
        return str(self.args.resource_group)

    @property
    def rg_id(self) -> str:
        return f"/subscriptions/{self.sub}/resourceGroups/{self.rg}"

    @property
    def deployment_id(self) -> str:
        if self.args.deployment_id:
            return str(self.args.deployment_id)
        return "hosted-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", self.rg)[:100]

    @property
    def state_dir(self) -> Path:
        return Path(self.args.state_dir)

    def az(self, *args: str, parse: bool = True) -> Any:
        res = self.run_az(args)
        if res.rc != 0:
            raise AzError(f"az {' '.join(args[:3])} failed: {cm.g01().safe_text(res.stderr)}")
        if not parse:
            return None
        text = res.stdout.strip()
        return json.loads(text) if text else None

    def step(self, name: str, status: str, detail: str = "") -> None:
        self.steps.append({"step": name, "status": status, "detail": detail})
        print(f"[{status}] {name} {detail}".rstrip())

    def approve(self, tokens: Sequence[str]) -> None:
        now = cm.iso(cm.utcnow())
        for t in tokens:
            self.approvals.append({"token": t, "operator": str(self.args.operator), "utc": now})

    def require_tokens(self, given: str, needed: Sequence[str]) -> None:
        try:
            tokens = cm.parse_shared(given)
        except ValueError as exc:
            raise RefusedError(str(exc)) from exc
        missing = [t for t in needed if t not in tokens]
        if missing:
            raise RefusedError(
                f"missing --approve-shared token(s): {','.join(missing)}. No changes made."
            )
        self.approve(needed)


def _is_gov(location: str) -> bool:
    return location.strip().lower().startswith(_GOV_PREFIXES)


def validate_static(args: argparse.Namespace) -> None:
    if not _GUID.fullmatch(args.subscription):
        raise RefusedError("--subscription must be a subscription id (guid)")
    if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", args.resource_group):
        raise RefusedError("--resource-group has unsupported characters")
    loc = args.location.strip().lower()
    if _is_gov(loc) or not re.fullmatch(r"[a-z0-9]+", loc):
        raise RefusedError(
            f"location {args.location!r} is not a Commercial region; Government regions "
            "(usgov*/usdod*) are refused. No changes made."
        )
    if args.command in MUTATING and not cm.OPERATOR_RE.fullmatch(args.operator or ""):
        raise RefusedError("--operator is required (a name or handle, not an email address)")


def guard_cloud(ctx: Ctx) -> None:
    cloud = ctx.az("cloud", "show", "--query", "name", "--output", "json")
    if cloud != "AzureCloud":
        raise RefusedError(f"active az cloud is {cloud!r}; the hosted demo is AzureCloud only")
    active = ctx.az("account", "show", "--query", "id", "--output", "json")
    if str(active).lower() != ctx.sub.lower():
        raise RefusedError("active az subscription does not match --subscription")


def _need(args: argparse.Namespace, names: Sequence[str]) -> None:
    missing = [n for n in names if not str(getattr(args, n, "") or "").strip()]
    if missing:
        flags = ", ".join("--" + n.replace("_", "-") for n in missing)
        raise RefusedError(f"missing required argument(s): {flags}")


def infra_values(ctx: Ctx) -> dict[str, Any]:
    a = ctx.args
    _need(a, _DEPLOY_REQUIRED)
    emails = [e.strip() for e in a.budget_emails.split(",") if e.strip()]
    try:
        amount = int(a.budget_amount)
    except ValueError as exc:
        raise RefusedError("--budget-amount must be a whole number") from exc
    return {
        "prefix": a.prefix,
        "location": a.location.strip().lower(),
        "imageRegistry": a.image_registry,
        "imageTag": a.image_tag,
        "appServiceSkuName": a.sku,
        "deployKeyVault": not a.no_key_vault,
        "integrationSubnetId": a.integration_subnet_id,
        "privateEndpointSubnetId": a.pe_subnet_id,
        "cosmosDnsZoneId": a.cosmos_zone_id,
        "eventHubsDnsZoneId": a.eventhubs_zone_id,
        "blobDnsZoneId": a.blob_zone_id,
        "webAppsDnsZoneId": a.webapps_zone_id,
        "keyVaultDnsZoneId": a.keyvault_zone_id,
        "entraTenantId": a.entra_tenant_id,
        "entraClientId": a.entra_client_id,
        "copilotEndpoint": a.copilot_endpoint,
        "copilotDeployment": a.copilot_deployment,
        "budgetAmount": amount,
        "budgetStartDate": a.budget_start_date or cm.default_budget_start(),
        "budgetContactEmails": emails,
        "tagOwner": a.tag_owner,
        "tagDeleteAfter": a.tag_delete_after or cm.default_delete_after(),
        "deploymentId": ctx.deployment_id,
        "createdBy": a.created_by,
    }


def rg_tags(ctx: Ctx, values: dict[str, Any]) -> list[str]:
    return [
        f"owner={values['tagOwner']}",
        "project=neurosphere",
        "env=demo",
        f"delete-after={values['tagDeleteAfter']}",
        f"neurosphere:created-by={values['createdBy']}",
        f"neurosphere:deployment-id={ctx.deployment_id}",
    ]


def ensure_resource_group(ctx: Ctx, values: dict[str, Any]) -> bool:
    exists = ctx.az("group", "exists", "--name", ctx.rg, "--subscription", ctx.sub, "-o", "json")
    if exists is True:
        ctx.step("resource-group", "ok", f"{ctx.rg} already exists")
        return False
    ctx.az(
        "group",
        "create",
        "--name",
        ctx.rg,
        "--location",
        str(values["location"]),
        "--subscription",
        ctx.sub,
        "--tags",
        *rg_tags(ctx, values),
        "--output",
        "json",
    )
    ctx.step("resource-group-create", "ok", ctx.rg)
    return True


def write_params_file(ctx: Ctx, values: dict[str, Any]) -> Path:
    ctx.work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="hosted-params-", suffix=".json", dir=ctx.work_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(cm.build_parameters(values), handle)
    return Path(name)


def _deployment_args(ctx: Ctx, verb: str, params: Path) -> list[str]:
    return [
        "deployment",
        "group",
        verb,
        "--resource-group",
        ctx.rg,
        "--subscription",
        ctx.sub,
        "--name",
        cm.DEPLOYMENT_NAME,
        "--template-file",
        cm.TEMPLATE,
        "--parameters",
        f"@{params}",
        "--output",
        "json",
    ]


def run_what_if(ctx: Ctx, params: Path) -> tuple[list[dict[str, str]], str]:
    out = ctx.az(*_deployment_args(ctx, "what-if", params), "--no-pretty-print")
    changes = cm.normalize_changes(out)
    digest = cm.changes_hash(changes)
    counts = cm.summarize_changes(changes)
    ctx.step("what-if", "ok", f"{len(changes)} change(s) {counts}")
    return changes, digest


def get_outputs(ctx: Ctx) -> dict[str, Any]:
    raw = ctx.az(
        "deployment",
        "group",
        "show",
        "--resource-group",
        ctx.rg,
        "--subscription",
        ctx.sub,
        "--name",
        cm.DEPLOYMENT_NAME,
        "--query",
        "properties.outputs",
        "--output",
        "json",
    )
    return flatten_outputs(raw)


def flatten_outputs(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, body in (raw or {}).items():
        out[str(name)] = body.get("value") if isinstance(body, dict) else body
    return out


# --------------------------------------------------------------------------- register rows


def make_row(
    ctx: Ctx,
    resource_id: str,
    service: str,
    *,
    created: bool,
    consent: str | None = None,
    ownership: str = "reused",
) -> Any:
    from neurosphere_core.deploy.register import Ownership, ResourceRow

    if created:
        kind, by, consent_ref = Ownership.CREATED, "neurosphere", None
    else:
        kind = Ownership.SHARED if ownership == "shared" else Ownership.REUSED
        by, consent_ref = None, consent or "operator-approved"
    return ResourceRow(
        deployment_id=ctx.deployment_id,
        resource_id=resource_id,
        service=service[:64],
        ownership=kind,
        created_by=by,
        owner=str(ctx.args.operator),
        consent_reference=consent_ref,
        creating_plan_id=cm.DEPLOYMENT_NAME,
        recorded_at=cm.utcnow(),
    )


def open_book(ctx: Ctx, endpoint: str = "", database: str = "") -> cm.RegisterBook:
    backend = None
    if endpoint and database:
        try:
            backend = ctx.backend_factory(endpoint, database)
        except Exception:
            backend = None
    return cm.RegisterBook(ctx.deployment_id, ctx.state_dir, backend)


def backend_target_from_registration(ctx: Ctx) -> tuple[str, str]:
    try:
        reg = json.loads((ctx.state_dir / "registration.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    host = str(reg.get("cosmos_host") or "")
    return (f"https://{host}:443/" if host else ""), str(reg.get("database") or "")


def list_rg_resources(ctx: Ctx) -> list[dict[str, str]]:
    out = ctx.az(
        "resource", "list", "--resource-group", ctx.rg, "--subscription", ctx.sub, "-o", "json"
    )
    found: list[dict[str, str]] = []
    for item in out or []:
        if isinstance(item, dict):
            rid = str(item.get("id", ""))
            found.append({"id": rid, "type": str(item.get("type") or cm.resource_type(rid))})
    return found


# --------------------------------------------------------------------------- preflight


def _check(ctx: Ctx, checks: list[dict[str, Any]], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"check": name, "ok": ok, "detail": detail})
    ctx.step(f"preflight:{name}", "ok" if ok else "failed", detail)


def _outbound_internet_deny(nsg: dict[str, Any]) -> bool:
    for rule in nsg.get("securityRules") or []:
        if str(rule.get("direction")).lower() != "outbound":
            continue
        if str(rule.get("access")).lower() != "deny":
            continue
        dests = [
            rule.get("destinationAddressPrefix"),
            *(rule.get("destinationAddressPrefixes") or []),
        ]
        if any(str(d).lower() in ("internet", "*", "0.0.0.0/0") for d in dests if d):
            return True
    return False


def cmd_preflight(ctx: Ctx) -> None:
    a = ctx.args
    _need(
        a,
        (
            "integration_subnet_id",
            "pe_subnet_id",
            "cosmos_zone_id",
            "eventhubs_zone_id",
            "blob_zone_id",
            "webapps_zone_id",
            "keyvault_zone_id",
            "foundry_account_id",
        ),
    )
    checks: list[dict[str, Any]] = []
    for ns in _PROVIDERS:
        state = ctx.az(
            "provider", "show", "--namespace", ns, "--query", "registrationState", "-o", "json"
        )
        _check(ctx, checks, f"provider:{ns}", state == "Registered", str(state))
    subnet = (
        ctx.az("network", "vnet", "subnet", "show", "--ids", a.integration_subnet_id, "-o", "json")
        or {}
    )
    delegations = {str(d.get("serviceName")) for d in subnet.get("delegations") or []}
    _check(ctx, checks, "subnet-delegated", "Microsoft.Web/serverFarms" in delegations)
    links = subnet.get("serviceAssociationLinks") or []
    ips = subnet.get("ipConfigurations") or []
    _check(ctx, checks, "subnet-empty", not links and not ips, f"links={len(links)} ips={len(ips)}")
    _check(ctx, checks, "subnet-no-route-table", not subnet.get("routeTable"))
    _check(ctx, checks, "subnet-default-outbound", subnet.get("defaultOutboundAccess") is not False)
    nsg = (subnet.get("networkSecurityGroup") or {}).get("id")
    if nsg:
        nsg_body = ctx.az("network", "nsg", "show", "--ids", str(nsg), "-o", "json") or {}
        _check(ctx, checks, "nsg-outbound-internet", not _outbound_internet_deny(nsg_body))
    else:
        _check(ctx, checks, "nsg-outbound-internet", True, "no NSG")
    ctx.az("network", "vnet", "subnet", "show", "--ids", a.pe_subnet_id, "-o", "json")
    _check(ctx, checks, "pe-subnet-present", True)
    zone_args = {
        "cosmosDnsZoneId": a.cosmos_zone_id,
        "eventHubsDnsZoneId": a.eventhubs_zone_id,
        "blobDnsZoneId": a.blob_zone_id,
        "webAppsDnsZoneId": a.webapps_zone_id,
        "keyVaultDnsZoneId": a.keyvault_zone_id,
    }
    for param, zone_id in zone_args.items():
        expected = cm.HUB_ZONES[param]
        name = cm.parse_arm_id(zone_id).get("name", "").lower()
        ctx.az("network", "private-dns", "zone", "show", "--ids", zone_id, "-o", "json")
        _check(ctx, checks, f"zone:{expected}", name == expected, "present")
    parsed = cm.parse_arm_id(a.foundry_account_id)
    deployments = ctx.az(
        "cognitiveservices",
        "account",
        "deployment",
        "list",
        "--resource-group",
        parsed.get("resource_group", ""),
        "--name",
        parsed.get("name", ""),
        "--subscription",
        parsed.get("subscription", ctx.sub),
        "--query",
        "[].name",
        "-o",
        "json",
    )
    _check(ctx, checks, "foundry-deployment", a.copilot_deployment in (deployments or []))
    ctx.details["checks"] = checks
    if not all(c["ok"] for c in checks):
        ctx.errors.append("one or more preflight checks failed")


# --------------------------------------------------------------------------- plan / status


def cmd_plan(ctx: Ctx) -> None:
    values = infra_values(ctx)
    ensure_resource_group(ctx, values)
    params = write_params_file(ctx, values)
    try:
        changes, digest = run_what_if(ctx, params)
    finally:
        params.unlink(missing_ok=True)
    ctx.details.update(
        plan_sha256=digest, change_counts=cm.summarize_changes(changes), changes=changes
    )
    print(f"PLAN SHA256: {digest}")
    print("Re-run `deploy` with --approve-plan <that hash> and --approve-shared tokens.")


def cmd_status(ctx: Ctx) -> None:
    values = infra_values(ctx)
    tags = ctx.az(
        "group",
        "show",
        "--name",
        ctx.rg,
        "--subscription",
        ctx.sub,
        "--query",
        "tags",
        "-o",
        "json",
    )
    params = write_params_file(ctx, values)
    try:
        changes, digest = run_what_if(ctx, params)
    finally:
        params.unlink(missing_ok=True)
    drift = [c for c in changes if c["changeType"] != "NoChange"]
    delete_after = (tags or {}).get("delete-after", "unset")
    ctx.details.update(drift_count=len(drift), plan_sha256=digest, delete_after=delete_after)
    ctx.step("status", "ok", f"drift={len(drift)} delete-after={delete_after}")


# --------------------------------------------------------------------------- deploy


def ensure_pseudonym_secret(ctx: Ctx, vault: str, secret_name: str) -> None:
    """D4: create the secret once, from a local value, via a temp file. Never overwrites."""
    names = ctx.az(
        "keyvault", "secret", "list", "--vault-name", vault, "--query", "[].name", "-o", "json"
    )
    if secret_name in (names or []):
        ctx.step("pseudonym-key", "ok", "already present; left untouched")
        ctx.details["pseudonym_value_stored"] = "existing"
        return
    path = cm.write_secret_file(ctx.work_dir, cm.new_pseudonym_value())
    try:
        ctx.az(
            "keyvault",
            "secret",
            "set",
            "--vault-name",
            vault,
            "--name",
            secret_name,
            "--file",
            str(path),
            "--encoding",
            "utf-8",
            "-o",
            "none",
            parse=False,
        )
    finally:
        path.unlink(missing_ok=True)
    ctx.step("pseudonym-key", "ok", "created from a locally generated value")
    ctx.details["pseudonym_value_stored"] = "created"


def _host(value: Any) -> str:
    text = str(value or "")
    return (urlsplit(text if "//" in text else f"//{text}").hostname or "") if text else ""


def write_registration(ctx: Ctx, out: dict[str, Any]) -> Path:
    vault = str(out.get("keyVaultName") or "")
    vault_host = f"{vault}.vault.azure.net" if vault else ""
    secret = str(out.get("pseudonymSecretName") or "")
    reg = {
        "schema": 1,
        "deployment_id": ctx.deployment_id,
        "cloud": "AzureCloud",
        "cosmos_host": _host(out.get("cosmosEndpoint")),
        "eventhubs_host": _host(out.get("eventHubsFqdn")),
        "blob_host": f"{out.get('storageAccountName', '')}.blob.core.windows.net",
        "key_vault_host": vault_host,
        "database": str(out.get("cosmosDatabaseName") or ""),
        "event_hub": str(out.get("eventHubName") or ""),
        "archive_container": str(out.get("archiveContainerName") or ""),
        "pseudonym_secret_uri": f"https://{vault_host}/secrets/{secret}"
        if vault_host and secret
        else "",
        "workers_object_id": str(out.get("workersPrincipalId") or ""),
        "customer_id": str(getattr(ctx.args, "customer_id", "synthco")),
    }
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.state_dir / "registration.json"
    path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
    return path


def post_check_sites(ctx: Ctx, out: dict[str, Any]) -> None:
    """Re-read each site: a management-group Modify policy can flip publicNetworkAccess."""
    a = ctx.args
    sites = (
        ("web", "frontendSiteName", "Enabled", "frontend"),
        ("api", "apiSiteName", "Disabled", "api"),
        ("workers", "workersSiteName", "Disabled", "workers"),
    )
    for label, key, want_public, image in sites:
        name = str(out.get(key) or "")
        info = (
            ctx.az(
                "webapp",
                "show",
                "--resource-group",
                ctx.rg,
                "--name",
                name,
                "--subscription",
                ctx.sub,
                "--query",
                "{publicNetworkAccess:publicNetworkAccess,linuxFxVersion:siteConfig.linuxFxVersion}",
                "-o",
                "json",
            )
            or {}
        )
        public = str(info.get("publicNetworkAccess"))
        want_image = f"DOCKER|{a.image_registry}/{image}:{a.image_tag}".lower()
        got_image = str(info.get("linuxFxVersion", "")).lower()
        ok_public = public == want_public
        ok_image = got_image == want_image
        ctx.step(
            f"post-check:{label}",
            "ok" if ok_public and ok_image else "failed",
            f"publicNetworkAccess={public} image_match={ok_image}",
        )
        if not ok_public:
            ctx.errors.append(
                f"{label} site publicNetworkAccess is {public}, expected {want_public}"
            )
        if not ok_image:
            ctx.errors.append(f"{label} site image reference does not match the pinned image")


def budget_ids(ctx: Ctx) -> list[str]:
    url = f"{_ARM_API}{ctx.rg_id}/providers/Microsoft.Consumption/budgets?api-version={_BUDGET_API}"
    res = ctx.run_az(
        ["rest", "--method", "get", "--url", url, "--query", "value[].id", "-o", "json"]
    )
    if res.rc != 0 or not res.stdout.strip():
        return []
    ids = json.loads(res.stdout)
    return [str(i) for i in ids] if isinstance(ids, list) else []


def cmd_deploy(ctx: Ctx) -> None:
    a = ctx.args
    ctx.require_tokens(a.approve_shared, cm.DEPLOY_SHARED)
    values = infra_values(ctx)
    exists = ctx.az("group", "exists", "--name", ctx.rg, "--subscription", ctx.sub, "-o", "json")
    if exists is not True:
        raise RefusedError("resource group does not exist; run `plan` first. No changes made.")
    params = write_params_file(ctx, values)
    try:
        changes, digest = run_what_if(ctx, params)
        ctx.details.update(plan_sha256=digest, change_counts=cm.summarize_changes(changes))
        if not a.approve_plan:
            print(f"PLAN SHA256: {digest}")
            raise RefusedError("deploy requires --approve-plan <sha256 of the what-if change list>")
        if a.approve_plan.strip().lower() != digest:
            raise RefusedError(
                "the what-if change list no longer matches --approve-plan "
                f"(now {digest}); nothing was created. Re-run `plan` and re-approve."
            )
        ctx.approvals.append(
            {"token": "plan-hash", "operator": str(a.operator), "utc": cm.iso(cm.utcnow())}
        )
        result = ctx.az(*_deployment_args(ctx, "create", params))
    finally:
        params.unlink(missing_ok=True)
    props = (result or {}).get("properties", {}) if isinstance(result, dict) else {}
    state = str(props.get("provisioningState", "Unknown"))
    out = flatten_outputs(props.get("outputs"))
    ctx.step("deployment-create", "ok" if state == "Succeeded" else "failed", state)
    if state != "Succeeded":
        ctx.errors.append(f"deployment ended in state {state}")
        return
    ctx.details["output_names"] = sorted(out)

    resources = list_rg_resources(ctx)
    rows = [make_row(ctx, ctx.rg_id, "Microsoft.Resources/resourceGroups", created=True)]
    rows += [make_row(ctx, r["id"], r["type"], created=True) for r in resources]
    for rid in budget_ids(ctx):
        rows.append(make_row(ctx, rid, "Microsoft.Consumption/budgets", created=True))
    for rid, token in (
        (a.integration_subnet_id, "hub-subnet"),
        (a.pe_subnet_id, "hub-pe"),
        (a.cosmos_zone_id, "hub-dns"),
        (a.eventhubs_zone_id, "hub-dns"),
        (a.blob_zone_id, "hub-dns"),
        (a.webapps_zone_id, "hub-dns"),
        *(((a.keyvault_zone_id, "hub-dns"),) if a.keyvault_zone_id else ()),
    ):
        rows.append(
            make_row(
                ctx,
                rid,
                "hub-shared",
                created=False,
                ownership="shared",
                consent=f"approve-shared:{token}",
            )
        )
    endpoint = str(out.get("cosmosEndpoint") or "")
    book = open_book(ctx, endpoint, str(out.get("cosmosDatabaseName") or ""))
    book.add(rows)
    problems = book.save()
    ctx.step(
        "register", "failed" if problems else "ok", f"{len(rows)} rows; " + "; ".join(problems)
    )
    ctx.errors.extend(problems)
    path = write_registration(ctx, out)
    ctx.step("registration", "ok", path.name)

    vault = str(out.get("keyVaultName") or "")
    if vault:
        try:
            ensure_pseudonym_secret(ctx, vault, str(out.get("pseudonymSecretName") or ""))
        except AzError as exc:
            ctx.errors.append(str(exc))
            ctx.step("pseudonym-key", "failed", str(exc))
    try:
        post_check_sites(ctx, out)
    except AzError as exc:
        ctx.errors.append(str(exc))


# --------------------------------------------------------------------------- shared steps


def cmd_grant_model_access(ctx: Ctx) -> None:
    a = ctx.args
    ctx.require_tokens(a.approve_shared, ("foundry-role",))
    out = get_outputs(ctx)
    principal = str(out.get("apiPrincipalId") or "")
    if not principal:
        raise RefusedError("deployment has no apiPrincipalId output")
    scope = a.foundry_account_id
    existing = ctx.az(
        "role",
        "assignment",
        "list",
        "--assignee",
        principal,
        "--role",
        cm.OPENAI_USER_ROLE,
        "--scope",
        scope,
        "--query",
        "[].id",
        "-o",
        "json",
    )
    if existing:
        ctx.step("foundry-role", "ok", "assignment already present; not registered as ours")
        return
    created = ctx.az(
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        principal,
        "--assignee-principal-type",
        "ServicePrincipal",
        "--role",
        cm.OPENAI_USER_ROLE,
        "--scope",
        scope,
        "-o",
        "json",
    )
    rid = str((created or {}).get("id", ""))
    ctx.step("foundry-role", "ok", "Cognitive Services OpenAI User assigned")
    book = _book_for_update(ctx)
    book.add(
        [
            make_row(
                ctx,
                scope,
                "foundry-account",
                created=False,
                ownership="shared",
                consent="approve-shared:foundry-role",
            ),
            make_row(ctx, rid, "foundry-role", created=True),
        ]
    )
    ctx.errors.extend(book.save())


def _book_for_update(ctx: Ctx) -> cm.RegisterBook:
    endpoint, database = backend_target_from_registration(ctx)
    book = open_book(ctx, endpoint, database)
    book.load()
    return book


def cmd_entra_redirect(ctx: Ctx) -> None:
    a = ctx.args
    ctx.require_tokens(a.approve_shared, ("entra-app",))
    out = get_outputs(ctx)
    host = str(out.get("frontendHostName") or "")
    if not host:
        raise RefusedError("deployment has no frontendHostName output")
    redirect = f"https://{host}/"
    query = f"/applications(appId='{a.entra_client_id}')?$select=id,spa"
    app = ctx.az("rest", "--method", "get", "--url", f"{_GRAPH}{query}", "-o", "json") or {}
    object_id = str(app.get("id", ""))
    prior = [str(u) for u in (app.get("spa") or {}).get("redirectUris") or []]
    state_file = ctx.state_dir / f"entra-prior-{ctx.deployment_id}.json"
    added = redirect not in prior
    if added and not state_file.exists():
        ctx.state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"app_object_id": object_id, "prior_spa_redirect_uris": prior}, indent=2),
            encoding="utf-8",
        )
    if not added:
        ctx.step("entra-redirect", "ok", "redirect already present; nothing sent")
        return
    _patch_spa(ctx, object_id, [*prior, redirect])
    ctx.step("entra-redirect", "ok", f"added 1 redirect; {len(prior)} prior saved for restore")


def _patch_spa(ctx: Ctx, object_id: str, uris: list[str]) -> None:
    ctx.work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="entra-", suffix=".json", dir=ctx.work_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"spa": {"redirectUris": uris}}, handle)
    try:
        ctx.az(
            "rest",
            "--method",
            "patch",
            "--url",
            f"{_GRAPH}/applications/{object_id}",
            "--headers",
            "Content-Type=application/json",
            "--body",
            f"@{name}",
            parse=False,
        )
    finally:
        Path(name).unlink(missing_ok=True)


def _seed_scopes(ctx: Ctx, out: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(kind, role, scope) for the four seeder grants, all on NeuroSphere-owned resources."""
    base = f"{ctx.rg_id}/providers"
    return [
        ("cosmos", cm.COSMOS_DATA_CONTRIBUTOR, f"/dbs/{out.get('cosmosDatabaseName')}"),
        (
            "rbac",
            cm.EVENTHUBS_SENDER_ROLE,
            f"{base}/Microsoft.EventHub/namespaces/{out.get('eventHubsNamespaceName')}"
            f"/eventhubs/{out.get('eventHubName')}",
        ),
        (
            "rbac",
            cm.BLOB_CONTRIBUTOR_ROLE,
            f"{base}/Microsoft.Storage/storageAccounts/{out.get('storageAccountName')}"
            f"/blobServices/default/containers/{out.get('archiveContainerName')}",
        ),
        (
            "rbac",
            cm.KEYVAULT_SECRETS_USER_ROLE,
            f"{base}/Microsoft.KeyVault/vaults/{out.get('keyVaultName')}"
            f"/secrets/{out.get('pseudonymSecretName')}",
        ),
    ]


def cmd_seed_access(ctx: Ctx) -> None:
    a = ctx.args
    out = get_outputs(ctx)
    account = str(out.get("cosmosAccountName") or "")
    book = _book_for_update(ctx)
    if not book.load():
        raise RefusedError("ownership register not readable; refusing to touch role assignments")
    owned = {r.resource_id.lower() for r in book.rows if r.created_by == "neurosphere"}
    needed = [
        f"{ctx.rg_id}/providers/Microsoft.DocumentDB/databaseAccounts/{account}",
        f"{ctx.rg_id}/providers/Microsoft.EventHub/namespaces/{out.get('eventHubsNamespaceName')}",
        f"{ctx.rg_id}/providers/Microsoft.Storage/storageAccounts/{out.get('storageAccountName')}",
        f"{ctx.rg_id}/providers/Microsoft.KeyVault/vaults/{out.get('keyVaultName')}",
    ]
    foreign = [n for n in needed if n.lower() not in owned]
    if foreign:
        raise RefusedError(
            "seed grants are limited to NeuroSphere-created resources in the register"
        )
    ids: list[str] = []
    for kind, role, scope in _seed_scopes(ctx, out):
        if a.grant:
            created = _grant_one(ctx, kind, role, scope, account, a.principal)
            if created:
                ids.append(created)
        else:
            _revoke_one(ctx, kind, role, scope, account, a.principal)
    if a.grant:
        ctx.details["expires_hint_hours"] = a.expires_hours
        ctx.step("seed-access", "ok", f"granted; revoke within {a.expires_hours}h with --revoke")
        book.add([make_row(ctx, rid, "seed-access", created=True) for rid in ids])
        ctx.errors.extend(book.save())
    else:
        ctx.step("seed-access", "ok", "revoked")


def _cosmos_assignments(ctx: Ctx, account: str, principal: str, scope_suffix: str) -> list[str]:
    rows = (
        ctx.az(
            "cosmosdb",
            "sql",
            "role",
            "assignment",
            "list",
            "--account-name",
            account,
            "--resource-group",
            ctx.rg,
            "--subscription",
            ctx.sub,
            "-o",
            "json",
        )
        or []
    )
    return [
        str(r.get("id", ""))
        for r in rows
        if str(r.get("principalId", "")).lower() == principal.lower()
        and str(r.get("roleDefinitionId", "")).lower().endswith(cm.COSMOS_DATA_CONTRIBUTOR)
        and str(r.get("scope", "")).lower().endswith(scope_suffix.lower())
    ]


def _grant_one(ctx: Ctx, kind: str, role: str, scope: str, account: str, principal: str) -> str:
    if kind == "cosmos":
        if _cosmos_assignments(ctx, account, principal, scope):
            ctx.step("grant:cosmos", "ok", "already present")
            return ""
        made = ctx.az(
            "cosmosdb",
            "sql",
            "role",
            "assignment",
            "create",
            "--account-name",
            account,
            "--resource-group",
            ctx.rg,
            "--subscription",
            ctx.sub,
            "--scope",
            scope,
            "--principal-id",
            principal,
            "--role-definition-id",
            role,
            "-o",
            "json",
        )
        ctx.step("grant:cosmos", "ok", "Data Contributor at database scope")
        return str((made or {}).get("id", ""))
    existing = ctx.az(
        "role",
        "assignment",
        "list",
        "--assignee",
        principal,
        "--role",
        role,
        "--scope",
        scope,
        "--query",
        "[].id",
        "-o",
        "json",
    )
    if existing:
        ctx.step("grant:rbac", "ok", "already present")
        return ""
    made = ctx.az(
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        principal,
        "--assignee-principal-type",
        "User",
        "--role",
        role,
        "--scope",
        scope,
        "-o",
        "json",
    )
    ctx.step("grant:rbac", "ok", f"role {role[:8]} granted")
    return str((made or {}).get("id", ""))


def _revoke_one(ctx: Ctx, kind: str, role: str, scope: str, account: str, principal: str) -> None:
    if kind == "cosmos":
        for rid in _cosmos_assignments(ctx, account, principal, scope):
            delete_cosmos_assignment(ctx, rid, account)
        ctx.step("revoke:cosmos", "ok")
        return
    ids = ctx.az(
        "role",
        "assignment",
        "list",
        "--assignee",
        principal,
        "--role",
        role,
        "--scope",
        scope,
        "--query",
        "[].id",
        "-o",
        "json",
    )
    for rid in ids or []:
        ctx.az("role", "assignment", "delete", "--ids", str(rid), parse=False)
    ctx.step("revoke:rbac", "ok", f"role {role[:8]}")


def delete_cosmos_assignment(ctx: Ctx, assignment_id: str, account: str) -> None:
    ctx.az(
        "cosmosdb",
        "sql",
        "role",
        "assignment",
        "delete",
        "--account-name",
        account,
        "--resource-group",
        ctx.rg,
        "--subscription",
        ctx.sub,
        "--role-assignment-id",
        assignment_id.rsplit("/", 1)[-1],
        "--yes",
        parse=False,
    )


# --------------------------------------------------------------------------- smoke


def cmd_smoke(ctx: Ctx, smoke_module: Any) -> None:
    out = get_outputs(ctx)
    kwargs: dict[str, Any] = {
        "runner": ctx.run_az,
        "subscription": ctx.sub,
        "resource_group": ctx.rg,
        "frontend_host": str(out.get("frontendHostName") or ""),
        "api_host": str(out.get("apiHostName") or ""),
        "frontend_site": str(out.get("frontendSiteName") or ""),
        "api_site": str(out.get("apiSiteName") or ""),
        "workers_site": str(out.get("workersSiteName") or ""),
        "evidence_dir": Path(ctx.args.evidence_dir),
        "operator": str(ctx.args.operator),
    }
    func = smoke_module.run_smoke
    params = inspect.signature(func).parameters
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    result = func(**kwargs)
    ok = result is None or result is True or result == 0
    ctx.step("smoke", "ok" if ok else "failed", "delegated to _hosted_demo_smoke")
    if not ok:
        ctx.errors.append("smoke checks failed")


# --------------------------------------------------------------------------- teardown


class _LiveInventory:
    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx

    async def list_resource_group(self, rg_id: str) -> list[str]:
        _ = rg_id
        return [r["id"] for r in list_rg_resources(self._ctx)]


def _tolerant(ctx: Ctx, *args: str) -> None:
    res = ctx.run_az(args)
    if res.rc != 0 and not any(m in res.stderr.lower() for m in _NOT_FOUND):
        raise AzError(f"az {' '.join(args[:3])} failed: {cm.g01().safe_text(res.stderr)}")


def cmd_teardown(ctx: Ctx) -> None:
    from neurosphere_core.deploy.register import (
        assert_resource_group_empty_of_foreign,
        normalize_id,
        plan_removal,
    )
    from neurosphere_core.deploy.register.guard import foreign_live_ids, is_resource_group

    a = ctx.args
    if not a.confirm or a.confirm != ctx.deployment_id:
        raise RefusedError(
            f"--confirm must equal the deployment id ({ctx.deployment_id!r}); nothing removed"
        )
    endpoint, database = backend_target_from_registration(ctx)
    book = open_book(ctx, endpoint, database)
    if not book.load():
        raise RefusedError("neither register copy is readable; refusing to remove anything")
    rows = book.rows
    live = list_rg_resources(ctx)
    foreign = foreign_live_ids([r["id"] for r in live], rows)
    if foreign:
        raise RefusedError(
            f"resource group holds {len(foreign)} resource(s) the register does not own; "
            "nothing removed"
        )
    plan = plan_removal(ctx.deployment_id, rows, unregistered_ids=[r["id"] for r in live])
    removable = {normalize_id(e.resource_id) for e in plan.removable}
    by_id = {normalize_id(r.resource_id): r for r in rows}

    def rows_where(pred: Callable[[Any], bool]) -> list[Any]:
        return [r for k, r in by_id.items() if k in removable and pred(r)]

    def safe(row: Any) -> str:
        if normalize_id(row.resource_id) not in removable:
            raise RefusedError("attempted removal of a resource the register does not own")
        return str(row.resource_id)

    def rtype(r: Any) -> str:
        return cm.resource_type(r.resource_id)

    # 1. Entra redirect restore (our own earlier change on the shared app object).
    state_file = ctx.state_dir / f"entra-prior-{ctx.deployment_id}.json"
    if state_file.exists():
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        _patch_spa(ctx, str(saved["app_object_id"]), list(saved["prior_spa_redirect_uris"]))
        ctx.step("entra-restore", "ok", "prior spa redirect list restored")
    else:
        ctx.step("entra-restore", "skipped", "no recorded Entra change")
    # 2. Foundry role, 3. seeder roles (assignments we created).
    for service in ("foundry-role", "seed-access"):
        for row in rows_where(lambda r, s=service: r.service == s):
            rid = safe(row)
            if "/sqlroleassignments/" in rid.lower():
                account = cm.parse_arm_id(rid.split("/sqlRoleAssignments")[0]).get("name", "")
                try:
                    delete_cosmos_assignment(ctx, rid, account)
                except AzError as exc:
                    if not any(m in str(exc).lower() for m in _NOT_FOUND):
                        raise
            else:
                _tolerant(ctx, "role", "assignment", "delete", "--ids", rid)
        ctx.step(f"remove:{service}", "ok")
    # 4. VNet integration disconnect BEFORE any site deletion.
    sites = rows_where(lambda r: rtype(r) == "microsoft.web/sites")
    for row in sites:
        _tolerant(ctx, "webapp", "vnet-integration", "remove", "--ids", safe(row))
    ctx.step("vnet-integration-disconnect", "ok", f"{len(sites)} site(s)")
    # 5. Private endpoints, API first.
    pes = rows_where(lambda r: rtype(r) == "microsoft.network/privateendpoints")
    pes.sort(
        key=lambda r: ("api" not in cm.parse_arm_id(r.resource_id)["name"].lower(), r.resource_id)
    )
    for row in pes:
        _tolerant(ctx, "network", "private-endpoint", "delete", "--ids", safe(row))
    ctx.step("remove:private-endpoints", "ok", f"{len(pes)}")
    # 6. Sites and plan.
    for row in sites:
        _tolerant(ctx, "webapp", "delete", "--ids", safe(row))
    for row in rows_where(lambda r: rtype(r) == "microsoft.web/serverfarms"):
        _tolerant(ctx, "appservice", "plan", "delete", "--ids", safe(row), "--yes")
    ctx.step("remove:sites-and-plan", "ok")
    # 7. Data services (Key Vault: delete only, never purge).
    skip_types = {
        "microsoft.web/sites",
        "microsoft.web/serverfarms",
        "microsoft.network/privateendpoints",
        "microsoft.network/networkinterfaces",
        "microsoft.consumption/budgets",
    }
    for row in rows_where(lambda r: r.service not in ("foundry-role", "seed-access")):
        rid = safe(row)
        t = rtype(row)
        if is_resource_group(rid) or t in skip_types:
            continue
        if t == "microsoft.keyvault/vaults":
            name = cm.parse_arm_id(rid)["name"]
            _tolerant(
                ctx,
                "keyvault",
                "delete",
                "--name",
                name,
                "--resource-group",
                ctx.rg,
                "--subscription",
                ctx.sub,
            )
        else:
            _tolerant(ctx, "resource", "delete", "--ids", rid)
    ctx.step("remove:data-services", "ok", "Key Vault soft-deleted, not purged")
    # 8. Budget.
    for row in rows_where(lambda r: rtype(r) == "microsoft.consumption/budgets"):
        url = f"{_ARM_API}{safe(row)}?api-version={_BUDGET_API}"
        _tolerant(ctx, "rest", "--method", "delete", "--url", url)
    ctx.step("remove:budget", "ok")
    # 9. Resource group, only after a fresh check that nothing foreign lives in it.
    group_rows = rows_where(lambda r: is_resource_group(r.resource_id))
    if group_rows:
        asyncio.run(assert_resource_group_empty_of_foreign(ctx.rg_id, rows, _LiveInventory(ctx)))
        _tolerant(ctx, "group", "delete", "--name", ctx.rg, "--subscription", ctx.sub, "--yes")
        ctx.step("remove:resource-group", "ok", ctx.rg)
    else:
        ctx.step("remove:resource-group", "skipped", "group not removable per the register")
    ctx.details["shared_resources_untouched"] = sorted(
        r.resource_id for r in rows if r.created_by != "neurosphere"
    )


# --------------------------------------------------------------------------- orchestration

COMMANDS: dict[str, Callable[[Ctx], None]] = {
    "preflight": cmd_preflight,
    "plan": cmd_plan,
    "deploy": cmd_deploy,
    "grant-model-access": cmd_grant_model_access,
    "entra-redirect": cmd_entra_redirect,
    "seed-access": cmd_seed_access,
    "teardown": cmd_teardown,
    "status": cmd_status,
}


def _emit(ctx: Ctx, started: str, result: str) -> str:
    a = ctx.args
    evidence: dict[str, Any] = {
        "gate": cm.GATE,
        "command": a.command,
        "result": result,
        "script_version": cm.SCRIPT_VERSION,
        "started_utc": started,
        "finished_utc": cm.iso(cm.utcnow()),
        "operator": a.operator or "unspecified",
        "subscription_id": ctx.sub,
        "resource_group": ctx.rg,
        "location": a.location.strip().lower(),
        "deployment_id": ctx.deployment_id,
        "approvals": ctx.approvals,
        "steps": ctx.steps,
        "errors": ctx.errors,
        "details": ctx.details,
    }
    try:
        final = cm.finalize_evidence(evidence, ctx.sub)
    except cm.g01().ScrubError as exc:
        print(f"ERROR: evidence scrubber rejected the run: {exc}", file=sys.stderr)
        final = cm.redact_guids(
            {
                "gate": cm.GATE,
                "command": a.command,
                "result": "FAIL",
                "started_utc": started,
                "finished_utc": evidence["finished_utc"],
                "operator": evidence["operator"],
                "resource_group": ctx.rg,
                "location": evidence["location"],
                "approvals": ctx.approvals,
                "steps": [],
                "errors": ["evidence scrubber rejected the collected data (values withheld)"],
            }
        )
    path = cm.write_evidence(final, Path(a.evidence_dir), a.command)
    print(f"{final['result']}: wrote {path}")
    return str(final["result"])


def run(
    args: argparse.Namespace, runner: AzRunner, work_dir: Path, backend_factory: BackendFactory
) -> int:
    started = cm.iso(cm.utcnow())
    ctx = Ctx(run_az=runner, args=args, work_dir=work_dir, backend_factory=backend_factory)
    smoke_module: Any = None
    try:
        validate_static(args)
        if args.command == "smoke":
            try:
                smoke_module = importlib.import_module("_hosted_demo_smoke")
            except ImportError as exc:
                raise RefusedError(
                    "scripts/gates/_hosted_demo_smoke.py is not available (item 6 has not "
                    "landed); smoke cannot run. No az command was run."
                ) from exc
        guard_cloud(ctx)
        if args.command == "smoke":
            cmd_smoke(ctx, smoke_module)
        else:
            COMMANDS[args.command](ctx)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (AzError, ValueError, OSError, json.JSONDecodeError) as exc:
        ctx.errors.append(cm.g01().safe_text(str(exc)))
        ctx.step(args.command, "failed", cm.g01().safe_text(str(exc)))
    except Exception as exc:
        ctx.errors.append(f"{type(exc).__name__}: {cm.g01().safe_text(str(exc))}")
        ctx.step(args.command, "failed", type(exc).__name__)
    result = "FAIL" if ctx.errors else "PASS"
    return 0 if _emit(ctx, started, result) == "PASS" else 1


def main(
    argv: list[str] | None = None,
    *,
    runner: AzRunner | None = None,
    work_dir: Path | None = None,
    backend_factory: BackendFactory | None = None,
) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: hosted_demo.py deploys billable Azure resources and changes shared "
            "enterprise resources; it needs operator approval. Set NS_LIVE_APPROVED=1. "
            "No az command was run.",
            file=sys.stderr,
        )
        return 2
    args = build_parser().parse_args(argv)
    try:
        importlib.import_module("neurosphere_core.deploy.register")
    except ImportError:
        print(
            "REFUSED: neurosphere_core is not importable; run with `uv run python "
            "scripts/gates/hosted_demo.py ...`. No az command was run.",
            file=sys.stderr,
        )
        return 2
    if runner is None:
        az_path = shutil.which("az")
        if not az_path:
            print("REFUSED: the Azure CLI (az) was not found on PATH.", file=sys.stderr)
            return 2
        runner = SubprocessAzRunner(az_path)
    factory = backend_factory or _default_backend
    if work_dir is not None:
        return run(args, runner, work_dir, factory)
    with tempfile.TemporaryDirectory(prefix="hosted-demo-") as tmp:
        return run(args, runner, Path(tmp), factory)


if __name__ == "__main__":
    raise SystemExit(main())
