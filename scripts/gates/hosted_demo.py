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
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import httpx

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
_GUID_ARGS = ("entra_tenant_id", "entra_client_id", "principal")
_ARM_ID_ARGS = (
    "integration_subnet_id",
    "pe_subnet_id",
    "cosmos_zone_id",
    "eventhubs_zone_id",
    "blob_zone_id",
    "webapps_zone_id",
    "keyvault_zone_id",
    "foundry_account_id",
)
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


#: Evidence keeps the whole az error (a failed deployment lists every failing resource).
AZ_TEXT_LIMIT = 4000


def _az_text(text: str, limit: int = AZ_TEXT_LIMIT) -> str:
    """az error text for evidence: long limit; secret-pattern redaction still applies."""
    return str(cm.g01().safe_text(text, limit))


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
        p.add_argument(
            "--copilot-mode",
            dest="copilot_mode",
            choices=("disabled", "approved_endpoint", "foundry_agent"),
            default="disabled",
            help="copilotMode; stays disabled until a dated capability row exists (decision 5)",
        )
        p.add_argument(
            "--foundry-account-id",
            default="",
            help="Foundry account ARM id (bound into the plan hash when given)",
        )

    p = sub.add_parser("preflight", parents=[common], help="read-only checks")
    infra(p)
    p = sub.add_parser("plan", parents=[common], help="create the group, run what-if")
    infra(p)
    p = sub.add_parser("deploy", parents=[common], help="what-if again, then deploy")
    infra(p)
    p.add_argument("--approve-plan", default="", help="sha256 printed by `plan`")
    p.add_argument("--approve-shared", default="", help="comma list of shared-step tokens")
    p.add_argument(
        "--resume-failed",
        default="",
        metavar="DEPLOY_EVIDENCE_JSON",
        help="recover from a failed deploy: register what the prior plan created as ours",
    )
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
    smoke_transport: httpx.BaseTransport | None = None

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
            raise AzError(f"az {' '.join(args[:3])} failed: {_az_text(res.stderr)}")
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
    for attr in _GUID_ARGS:
        value = str(getattr(args, attr, "") or "")
        if value and not cm.is_guid(value):
            raise RefusedError(f"--{attr.replace('_', '-')} must be a guid. No changes made.")
    for attr in _ARM_ID_ARGS:
        value = str(getattr(args, attr, "") or "")
        if value and not cm.is_arm_id(value):
            raise RefusedError(
                f"--{attr.replace('_', '-')} must be a /subscriptions/... resource id. "
                "No changes made."
            )


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
        "copilotMode": a.copilot_mode,
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


def plan_state_path(ctx: Ctx) -> Path:
    return ctx.state_dir / f"plan-{ctx.deployment_id}.json"


def read_plan_state(ctx: Ctx) -> dict[str, Any]:
    try:
        data = json.loads(plan_state_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def write_plan_state(ctx: Ctx, digest: str, rg_created: bool) -> None:
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "deployment_id": ctx.deployment_id,
        "plan_sha256": digest,
        "created_rg": rg_created,
    }
    plan_state_path(ctx).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def rg_tag_matches(ctx: Ctx) -> bool:
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
    return isinstance(tags, dict) and tags.get("neurosphere:deployment-id") == ctx.deployment_id


def rg_is_ours(ctx: Ctx) -> bool:
    """True only if an earlier ``plan`` created this group and its tag still names us."""
    return read_plan_state(ctx).get("created_rg") is True and rg_tag_matches(ctx)


def ensure_resource_group(ctx: Ctx, values: dict[str, Any]) -> bool:
    """Create the group if absent. Returns True only when this deployment owns the group."""
    exists = ctx.az("group", "exists", "--name", ctx.rg, "--subscription", ctx.sub, "-o", "json")
    if exists is True:
        ours = rg_is_ours(ctx)
        ctx.step(
            "resource-group",
            "ok",
            f"{ctx.rg} already exists; "
            + ("created by this deployment" if ours else "pre-existing, will not be registered"),
        )
        return ours
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


def shared_material(ctx: Ctx) -> dict[str, str]:
    """Shared-resource parameters bound into the plan hash."""
    a = ctx.args
    return {
        "integrationSubnetId": a.integration_subnet_id,
        "privateEndpointSubnetId": a.pe_subnet_id,
        "cosmosDnsZoneId": a.cosmos_zone_id,
        "eventHubsDnsZoneId": a.eventhubs_zone_id,
        "blobDnsZoneId": a.blob_zone_id,
        "webAppsDnsZoneId": a.webapps_zone_id,
        "keyVaultDnsZoneId": a.keyvault_zone_id,
        "foundryAccountId": a.foundry_account_id,
        "entraClientId": a.entra_client_id,
    }


def run_what_if(ctx: Ctx, params: Path) -> tuple[list[dict[str, str]], str]:
    out = ctx.az(*_deployment_args(ctx, "what-if", params), "--no-pretty-print")
    changes = cm.normalize_changes(out)
    digest = cm.bind_hash(cm.changes_hash(changes), shared_material(ctx))
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


#: Types ARM creates implicitly (never in a what-if change list) when a Create'd parent needs them.
_IMPLICIT_CHILD_TYPES = {
    "microsoft.network/networkinterfaces": "microsoft.network/privateendpoints"
}


def classify_resources(
    resources: Sequence[dict[str, str]],
    *,
    pre_ids: set[str],
    create_ids: set[str],
    earlier_created: set[str],
    resumed: set[str] | frozenset[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    """Split live ids into (ours, not ours).

    Ours = already registered as created by an earlier run of this deployment, or new since the
    pre-deploy snapshot AND listed as Create in the approved what-if (or an implicit private
    endpoint NIC while a private endpoint was Create'd). Everything else is not ours.
    """
    create_types = {cm.resource_type(i) for i in create_ids}
    ours: set[str] = set()
    other: set[str] = set()
    for r in resources:
        key = r["id"].lower().rstrip("/")
        rtype = cm.resource_type(key)
        implicit = _IMPLICIT_CHILD_TYPES.get(rtype)
        if key in earlier_created or key in resumed:
            ours.add(key)
        elif key not in pre_ids and (
            key in create_ids or (implicit is not None and implicit in create_types)
        ):
            ours.add(key)
        else:
            other.add(key)
    return ours, other


# --------------------------------------------------------------------------- resume


class ResumeState(NamedTuple):
    """What ``--resume-failed`` proved: the file name and the prior plan's scrubbed Create ids."""

    source: str
    create_ids: frozenset[str]


def scrub_key(ctx: Ctx, resource_id: str) -> str:
    """An id as the evidence stores it: scrubbed like ``finalize_evidence``, lower-cased."""
    scrubbed = cm.finalize_evidence({"id": resource_id}, ctx.sub)["id"]
    return str(scrubbed).lower().rstrip("/")


def _load_json_object(path: Path, what: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RefusedError(f"{what} is not readable JSON ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise RefusedError(f"{what} is not a JSON object")
    return cast("dict[str, Any]", data)


def load_resume(ctx: Ctx) -> ResumeState:
    """Check every ``--resume-failed`` precondition. Raises RefusedError; changes nothing."""
    path = Path(ctx.args.resume_failed)
    failed = _load_json_object(path, "--resume-failed file")
    if failed.get("command") != "deploy" or failed.get("result") != "FAIL":
        raise RefusedError("--resume-failed must be the evidence of a deploy that ended FAIL")
    if failed.get("deployment_id") != ctx.deployment_id:
        raise RefusedError("--resume-failed evidence belongs to a different deployment id")
    if failed.get("resource_group") != ctx.rg:
        raise RefusedError("--resume-failed evidence belongs to a different resource group")
    if str(failed.get("subscription_id", "")).lower() != scrub_key(ctx, ctx.sub):
        raise RefusedError("--resume-failed evidence belongs to a different subscription")
    approvals = failed.get("approvals")
    if not any(isinstance(x, dict) and x.get("token") == "plan-hash" for x in approvals or []):
        raise RefusedError("--resume-failed evidence has no plan-hash approval")
    failed_details = failed.get("details")
    digest = str(
        failed_details.get("plan_sha256", "") if isinstance(failed_details, dict) else ""
    ).lower()
    if not digest:
        raise RefusedError("--resume-failed evidence records no plan_sha256")
    if not rg_is_ours(ctx):
        raise RefusedError(
            "resource group is not ours (no plan state or tag mismatch); nothing to resume"
        )
    create_ids: set[str] = set()
    for plan_path in sorted(Path(ctx.args.evidence_dir).glob("*-plan.json")):
        try:
            plan = _load_json_object(plan_path, "plan evidence")
        except RefusedError:
            continue
        details = plan.get("details")
        if plan.get("command") != "plan" or not isinstance(details, dict):
            continue
        if str(details.get("plan_sha256", "")).lower() != digest:
            continue
        for change in details.get("changes") or []:
            if isinstance(change, dict) and change.get("changeType") == "Create":
                create_ids.add(str(change.get("resourceId", "")).lower().rstrip("/"))
    if not create_ids:
        raise RefusedError(
            "no plan evidence with the failed deploy's plan_sha256 and its change list was "
            "found in --evidence-dir"
        )
    book = open_book(ctx)
    book.load()
    if any(r.created_by == "neurosphere" for r in book.rows):
        raise RefusedError("the local register already has created rows; nothing to resume")
    return ResumeState(path.name, frozenset(create_ids))


def resume_owned(ctx: Ctx, resume: ResumeState, live_ids: Sequence[str]) -> set[str]:
    """Live ids (lower-cased) the failed run created. A resource or budget is ours when its
    scrubbed id was a Create in the prior plan; a private-endpoint NIC is ours when its name is
    ``<pe>.nic.<id>`` for a private endpoint that was a Create there (a sibling such as
    ``<pe>2.nic.<id>`` or ``<pe>-x.nic.<id>`` is not)."""
    pe_names = {
        i.rsplit("/", 1)[-1]
        for i in resume.create_ids
        if cm.resource_type(i) == "microsoft.network/privateendpoints"
    }
    owned: set[str] = set()
    for rid in live_ids:
        key = rid.lower().rstrip("/")
        if scrub_key(ctx, key) in resume.create_ids:
            owned.add(key)
        elif cm.resource_type(key) == "microsoft.network/networkinterfaces" and any(
            key.rsplit("/", 1)[-1].startswith(f"{n}.nic.") for n in pe_names
        ):
            owned.add(key)
    return owned


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
    rg_created = ensure_resource_group(ctx, values)
    params = write_params_file(ctx, values)
    try:
        changes, digest = run_what_if(ctx, params)
    finally:
        params.unlink(missing_ok=True)
    write_plan_state(ctx, digest, rg_created)
    ctx.details["resource_group_created_by_plan"] = rg_created
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


def ensure_pseudonym_secret(ctx: Ctx, vault: str, secret_name: str) -> bool:
    """D4: create the secret once, from a local value, via a temp file. Never overwrites.

    Returns True only when this call created the secret (the sites then hold stale references).
    """
    names = ctx.az(
        "keyvault", "secret", "list", "--vault-name", vault, "--query", "[].name", "-o", "json"
    )
    if secret_name in (names or []):
        ctx.step("pseudonym-key", "ok", "already present; left untouched")
        ctx.details["pseudonym_value_stored"] = "existing"
        return False
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
    return True


_REFS_API_REFRESH = "2022-03-01"
_REFS_API_READ = "2023-12-01"


def refresh_key_vault_references(ctx: Ctx, out: dict[str, Any]) -> None:
    """Force App Service to re-resolve Key Vault references after the secret was created.

    References are cached for 24 h (a cached SecretNotFound survives a plain restart), so POST the
    refresh, restart, then re-read each reference. Only setting names and statuses are logged.
    """
    for key in ("apiSiteName", "workersSiteName"):
        name = str(out.get(key) or "")
        if not name:
            continue
        site_id = f"{ctx.rg_id}/providers/Microsoft.Web/sites/{name}"
        refs = f"{_ARM_API}{site_id}/config/configreferences/appsettings"
        label = f"kv-refs:{key.removesuffix('SiteName')}"
        try:
            ctx.az(
                "rest",
                "--method",
                "post",
                "--url",
                f"{refs}/refresh?api-version={_REFS_API_REFRESH}",
                "--subscription",
                ctx.sub,
                parse=False,
            )
            ctx.az(
                "webapp",
                "restart",
                "--resource-group",
                ctx.rg,
                "--name",
                name,
                "--subscription",
                ctx.sub,
                parse=False,
            )
            body = ctx.az(
                "rest",
                "--method",
                "get",
                "--url",
                f"{refs}?api-version={_REFS_API_READ}",
                "--subscription",
                ctx.sub,
            )
        except AzError as exc:
            ctx.errors.append(str(exc))
            ctx.step(label, "failed", "refresh, restart or read failed; see the evidence errors")
            continue
        items = body.get("value") if isinstance(body, dict) else None  # pyright: ignore[reportUnknownMemberType]
        bad: list[str] = []
        for item in items or []:
            status = str((item.get("properties") or {}).get("status", "unknown"))
            if status != "Resolved":
                bad.append(f"{item.get('name', 'unknown')}={status}")
        if bad or not items:
            detail = "not resolved: " + ", ".join(bad) if bad else "no references returned"
            ctx.errors.append(f"{label} {detail}")
            ctx.step(label, "failed", detail)
        else:
            ctx.step(label, "ok", f"{len(items)} reference(s) Resolved")


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


def budget_ids(ctx: Ctx, *, strict: bool = False) -> list[str]:
    """Budget ids in the group. ``strict`` raises on a failed listing: the pre-deploy snapshot
    must never read as "no budgets", or a foreign budget would be registered as created."""
    url = f"{_ARM_API}{ctx.rg_id}/providers/Microsoft.Consumption/budgets?api-version={_BUDGET_API}"
    res = ctx.run_az(
        ["rest", "--method", "get", "--url", url, "--query", "value[].id", "-o", "json"]
    )
    if res.rc != 0 and strict:
        raise AzError("could not list the group's budgets before deploying; nothing was created")
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
    resume = load_resume(ctx) if a.resume_failed else None
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
        # Ownership evidence is taken BEFORE anything is created: only what is new afterwards
        # (and was in the approved change list) can be registered as ours.
        rg_owned = rg_is_ours(ctx)
        pre_ids = {r["id"].lower().rstrip("/") for r in list_rg_resources(ctx)}
        pre_budgets = {i.lower().rstrip("/") for i in budget_ids(ctx, strict=True)}
        create_ids = {c["resourceId"] for c in changes if c["changeType"] == "Create"}
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

    endpoint = str(out.get("cosmosEndpoint") or "")
    book = open_book(ctx, endpoint, str(out.get("cosmosDatabaseName") or ""))
    book.load()
    earlier_created = {
        r.resource_id.lower().rstrip("/") for r in book.rows if r.created_by == "neurosphere"
    }
    resources = list_rg_resources(ctx)
    resumed: set[str] = set()
    resumed_budgets: set[str] = set()
    if resume is not None:
        resumed = resume_owned(ctx, resume, [r["id"] for r in resources])
        resumed_budgets = resume_owned(ctx, resume, budget_ids(ctx))
    created_ids, foreign_ids = classify_resources(
        resources,
        pre_ids=pre_ids,
        create_ids=create_ids,
        earlier_created=earlier_created,
        resumed=resumed,
    )
    if rg_owned:
        rows = [make_row(ctx, ctx.rg_id, "Microsoft.Resources/resourceGroups", created=True)]
    else:
        rows = [
            make_row(
                ctx,
                ctx.rg_id,
                "Microsoft.Resources/resourceGroups",
                created=False,
                consent="pre-existing-resource-group",
            )
        ]
    for r in resources:
        key = r["id"].lower().rstrip("/")
        if key in created_ids:
            rows.append(make_row(ctx, r["id"], r["type"], created=True))
        else:
            rows.append(
                make_row(ctx, r["id"], r["type"], created=False, consent="pre-existing-at-deploy")
            )
    for rid in budget_ids(ctx):
        key = rid.lower().rstrip("/")
        if key not in pre_budgets or key in earlier_created or key in resumed_budgets:
            rows.append(make_row(ctx, rid, "Microsoft.Consumption/budgets", created=True))
        else:
            rows.append(
                make_row(
                    ctx,
                    rid,
                    "Microsoft.Consumption/budgets",
                    created=False,
                    consent="pre-existing-at-deploy",
                )
            )
    if resume is not None:
        ctx.details["resumed_from"] = resume.source
        ctx.details["resume_registered_count"] = len(created_ids & resumed) + len(resumed_budgets)
    ctx.details["register_created_count"] = sum(1 for r in rows if r.created_by == "neurosphere")
    ctx.details["register_not_ours_count"] = len(foreign_ids) + (0 if rg_owned else 1)
    if foreign_ids or not rg_owned:
        ctx.step(
            "ownership",
            "ok",
            f"{len(foreign_ids)} pre-existing resource(s) recorded as not ours; "
            f"resource group {'created by this deployment' if rg_owned else 'pre-existing'}; "
            "teardown will refuse while foreign resources remain",
        )
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
            created = ensure_pseudonym_secret(ctx, vault, str(out.get("pseudonymSecretName") or ""))
            if created:
                refresh_key_vault_references(ctx, out)
        except AzError as exc:
            ctx.errors.append(str(exc))
            # Console line stays generic; the scrubbed evidence carries the az error.
            ctx.step("pseudonym-key", "failed", "Key Vault call failed; see the evidence errors")
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
    if not cm.is_guid(principal):
        raise RefusedError("apiPrincipalId output is not a guid")
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
    rid = assignment_id(created, "foundry-role")
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


def assignment_id(made: Any, what: str) -> str:
    """The id of a just-created role assignment; empty means it cannot be registered or removed."""
    rid = str(made.get("id", "")) if isinstance(made, dict) else ""  # pyright: ignore[reportUnknownMemberType]
    if not rid.startswith("/"):
        raise AzError(
            f"{what}: az returned no assignment id, so the assignment cannot be registered; "
            "it may exist in Azure and must be checked and removed by the operator"
        )
    return rid


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
    if not cm.is_guid(object_id):
        raise AzError("Graph returned an application object id that is not a guid")
    prior = [str(u) for u in (app.get("spa") or {}).get("redirectUris") or []]
    state_file = ctx.state_dir / f"entra-prior-{ctx.deployment_id}.json"
    added = redirect not in prior
    if added and not state_file.exists():
        ctx.state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "app_object_id": object_id,
                    "prior_spa_redirect_uris": prior,
                    "added_redirect_uri": redirect,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if not added:
        ctx.step("entra-redirect", "ok", "redirect already present; nothing sent")
        return
    _patch_spa(ctx, object_id, [*prior, redirect])
    ctx.step("entra-redirect", "ok", f"added 1 redirect; {len(prior)} prior saved for restore")


def _patch_spa(ctx: Ctx, object_id: str, uris: list[str]) -> None:
    if not cm.is_guid(object_id):
        raise AzError("application object id is not a guid; refusing to build a Graph URL")
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


def role_definition_id(ctx: Ctx, role: str) -> str:
    """Full built-in role-definition id; a bare GUID fails to resolve at some scopes."""
    return f"/subscriptions/{ctx.sub}/providers/Microsoft.Authorization/roleDefinitions/{role}"


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
    removed = 0
    try:
        for kind, role, scope in _seed_scopes(ctx, out):
            if a.grant:
                created = _grant_one(ctx, kind, role, scope, account, a.principal)
                if created:
                    ids.append(created)
            else:
                removed += _revoke_one(ctx, book, kind, role, scope, account, a.principal)
    except AzError:
        # Grants made before the failure are real: register them so teardown can remove them.
        if ids:
            book.add([make_row(ctx, rid, "seed-access", created=True) for rid in ids])
        if ids or removed:
            ctx.errors.extend(book.save())
        raise
    if a.grant:
        ctx.details["expires_hint_hours"] = a.expires_hours
        ctx.step("seed-access", "ok", f"granted; revoke within {a.expires_hours}h with --revoke")
        book.add([make_row(ctx, rid, "seed-access", created=True) for rid in ids])
        ctx.errors.extend(book.save())
    else:
        ctx.errors.extend(book.save())
        ctx.step("seed-access", "ok", f"revoked {removed} registered assignment(s)")


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
        return assignment_id(made, "seed-access cosmos")
    existing = ctx.az(
        "role",
        "assignment",
        "list",
        "--assignee",
        principal,
        "--role",
        role_definition_id(ctx, role),
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
        role_definition_id(ctx, role),
        "--scope",
        scope,
        "-o",
        "json",
    )
    ctx.step("grant:rbac", "ok", "role assignment granted")
    return assignment_id(made, "seed-access rbac")


def _revoke_one(
    ctx: Ctx, book: Any, kind: str, role: str, scope: str, account: str, principal: str
) -> int:
    """Delete only assignments that are live AND registered as created by seed-access."""
    registered = {
        r.resource_id.lower()
        for r in book.rows
        if r.created_by == "neurosphere" and r.service == "seed-access"
    }
    if kind == "cosmos":
        live = _cosmos_assignments(ctx, account, principal, scope)
    else:
        found = ctx.az(
            "role",
            "assignment",
            "list",
            "--assignee",
            principal,
            "--role",
            role_definition_id(ctx, role),
            "--scope",
            scope,
            "--query",
            "[].id",
            "-o",
            "json",
        )
        live = [str(x) for x in found or []]
    mine = [rid for rid in live if rid.lower() in registered]
    for rid in mine:
        if kind == "cosmos":
            delete_cosmos_assignment(ctx, rid, account)
        else:
            ctx.az("role", "assignment", "delete", "--ids", rid, parse=False)
        book.remove([rid])
    detail = f"removed {len(mine)}" if mine else "removed 0 (none registered)"
    ctx.step(f"revoke:{kind}", "ok", detail)
    return len(mine)


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


def cmd_smoke(ctx: Ctx) -> None:
    # Imported here (not at module top) so that a missing smoke module is a clean refusal in
    # `run`, before any az call.
    import _hosted_demo_smoke as sm

    out = get_outputs(ctx)
    frontend_host = str(out.get("frontendHostName") or "")
    api_host = str(out.get("apiHostName") or "")
    if not frontend_host or not api_host:
        raise RefusedError("deployment outputs lack frontendHostName/apiHostName")
    names = [str(out.get(k) or "") for k in ("frontendSiteName", "apiSiteName", "workersSiteName")]
    sites = [sm.SiteTarget(name=n, resource_group=ctx.rg) for n in names if n]

    def az_runner(args: Sequence[str]) -> sm.AzResult:
        res = ctx.run_az(args)
        return sm.AzResult(res.rc, res.stdout, res.stderr)

    result = sm.run_smoke(
        frontend_url=f"https://{frontend_host}",
        api_host=api_host,
        sites=sites,
        az_runner=az_runner,
        transport=ctx.smoke_transport,
    )
    for check in result.checks:
        ctx.step(f"smoke:{check.name}", "ok" if check.passed else "failed", check.detail)
    ctx.details["smoke"] = result.to_dict()
    if not result.ok:
        names_failed = [c.name for c in result.failures] or ["no checks ran"]
        ctx.errors.append("smoke checks failed: " + ", ".join(names_failed))


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
        raise AzError(f"az {' '.join(args[:3])} failed: {_az_text(res.stderr)}")


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
        object_id = str(saved["app_object_id"])
        added = str(saved["added_redirect_uri"])
        if not cm.is_guid(object_id):
            raise AzError("recorded application object id is not a guid")
        # Remove only the URI this deployment added; keep whatever else is there now.
        current_app = (
            ctx.az(
                "rest",
                "--method",
                "get",
                "--url",
                f"{_GRAPH}/applications/{object_id}?$select=id,spa",
                "-o",
                "json",
            )
            or {}
        )
        current = [str(u) for u in (current_app.get("spa") or {}).get("redirectUris") or []]
        remaining = [u for u in current if u != added]
        if len(remaining) == len(current):
            ctx.step("entra-restore", "ok", "added redirect already absent; nothing sent")
        else:
            _patch_spa(ctx, object_id, remaining)
            ctx.step("entra-restore", "ok", "removed the one redirect this deployment added")
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
    args: argparse.Namespace,
    runner: AzRunner,
    work_dir: Path,
    backend_factory: BackendFactory,
    smoke_transport: httpx.BaseTransport | None = None,
) -> int:
    started = cm.iso(cm.utcnow())
    ctx = Ctx(
        run_az=runner,
        args=args,
        work_dir=work_dir,
        backend_factory=backend_factory,
        smoke_transport=smoke_transport,
    )
    try:
        validate_static(args)
        if args.command == "smoke":
            try:
                importlib.import_module("_hosted_demo_smoke")
            except ImportError as exc:
                raise RefusedError(
                    "scripts/gates/_hosted_demo_smoke.py is not available (item 6 has not "
                    "landed); smoke cannot run. No az command was run."
                ) from exc
        guard_cloud(ctx)
        if args.command == "smoke":
            cmd_smoke(ctx)
        else:
            COMMANDS[args.command](ctx)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (AzError, ValueError, OSError, json.JSONDecodeError) as exc:
        ctx.errors.append(_az_text(str(exc), AZ_TEXT_LIMIT + 200))
        # The console names only the error type; the scrubbed text lands in the evidence.
        ctx.step(args.command, "failed", f"{type(exc).__name__}; see the evidence errors")
    except Exception as exc:
        ctx.errors.append(f"{type(exc).__name__}: {_az_text(str(exc), AZ_TEXT_LIMIT + 200)}")
        ctx.step(args.command, "failed", type(exc).__name__)
    result = "FAIL" if ctx.errors else "PASS"
    return 0 if _emit(ctx, started, result) == "PASS" else 1


def main(
    argv: list[str] | None = None,
    *,
    runner: AzRunner | None = None,
    work_dir: Path | None = None,
    backend_factory: BackendFactory | None = None,
    smoke_transport: httpx.BaseTransport | None = None,
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
        return run(args, runner, work_dir, factory, smoke_transport)
    with tempfile.TemporaryDirectory(prefix="hosted-demo-") as tmp:
        return run(args, runner, Path(tmp), factory, smoke_transport)


if __name__ == "__main__":
    raise SystemExit(main())
