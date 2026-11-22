"""Hosted real-tenant data: access plan, approved apply, worker bootstrap, verify (PRP-139 item 6).

    python scripts/gates/hosted_real_tenant.py access-plan   --foundry-account-ids <id,...> ...
    NS_LIVE_APPROVED=1 python scripts/gates/hosted_real_tenant.py access-apply \
        --approve-plan <hash> --approve-assignment <token> [--approve-assignment <token> ...]
    NS_LIVE_APPROVED=1 NS_ENV=prod NS_SANDBOX_HOSTED_DEPLOYMENT_ID=<id> NS_AUTH_TENANT_ID=<guid> \
        python scripts/gates/hosted_real_tenant.py bootstrap-worker --domain-ids <id,...>
    NS_LIVE_APPROVED=1 NS_SANDBOX_HOSTED_DEPLOYMENT_ID=<id> \
        python scripts/gates/hosted_real_tenant.py verify --api-audience <resource>

Real-tenant mode is Commercial only: a Government registration, ``NS_CLOUD=government`` or an
``az`` cloud other than ``AzureCloud`` is refused (exit 2), not bridged.

``access-plan`` is offline: it makes no Azure call and writes only the plan file. ``access-apply``
runs only the rows the operator approved by token, each one a role assignment at the scope of ONE
resource; it never creates, edits or deletes the governed resource. Every ``az`` call goes through
``AzRunner`` and every HTTP call through ``HttpFn`` so tests use fakes. On Git Bash, ``az`` mangles
``/subscriptions/...`` arguments: operators export ``MSYS_NO_PATHCONV=1`` (arguments here are lists,
never a shell string).

Evidence (``docs/evidence/PRP-139/<date>-access.json`` and ``<date>-verify.json``) holds counts,
states and reason codes only: no subscription id (a short hash, as G17), tenant id, host, resource
id, object id or token. The plan file lives under ``temp/`` and does hold scopes and object ids
(``access-apply`` needs them); it is not evidence and must not be committed.

Exit codes: 0 done, 1 a row failed or a source verified FAIL, 2 refused (nothing was contacted).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlencode

REPO: Final = Path(__file__).resolve().parents[2]
SANDBOX_SCRIPTS: Final = REPO / "scripts" / "sandbox"
DEFAULT_REGISTRATION: Final = REPO / "temp" / "hosted-demo" / "registration.json"
DEFAULT_PLAN_FILE: Final = REPO / "temp" / "hosted-real-tenant" / "access-plan.json"
EVIDENCE_DIR: Final = REPO / "docs" / "evidence" / "PRP-139"
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2
ENV_APPROVED: Final = "NS_LIVE_APPROVED"
ENV_DEPLOYMENT_ID: Final = "NS_SANDBOX_HOSTED_DEPLOYMENT_ID"
ENV_CLOUD: Final = "NS_CLOUD"
ENV_DATA_MODE: Final = "NS_HOSTED_DATA_MODE"
GOVERNMENT_CLOUD_NAMES: Final = frozenset({"government", "usgovernment", "azureusgovernment"})
DEFAULT_PROPAGATION_SECONDS: Final = 600  # Learn: a role assignment can take up to 10 minutes
DEFAULT_RETRY_INTERVAL_SECONDS: Final = 30
UNVERIFIED: Final = "UNVERIFIED"

GUID_RE: Final = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
#: One resource id: subscription, resource group, ONE provider type and ONE name. Anything with
#: fewer segments (subscription, resource group, management group) or more (child resource) fails.
_RESOURCE_ID_RE: Final = re.compile(
    r"^/subscriptions/(?P<sub>[0-9a-fA-F-]{36})/resourceGroups/(?P<rg>[^/\s]+)"
    r"/providers/(?P<ns>[^/\s]+)/(?P<type>[^/\s]+)/(?P<name>[^/\s]+)$",
    re.IGNORECASE,
)
_DOMAIN_ID_RE: Final = re.compile(
    r"^(commercial):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$", re.ASCII
)
_HOST_RE: Final = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


@dataclass(frozen=True)
class RoleSpec:
    """One row of the role table. ``verified`` False means the role id was never checked."""

    source: str
    identity: str  # "workers" | "api"
    role_name: str
    role_definition_id: str
    verified: bool
    resource_type: str  # "<Namespace>/<type>", lower case
    flag: str  # the CLI flag that names the resource


#: Verified against Microsoft Learn on 2026-11-21. A later change is one line. The same ids go into
#: ``infra/demo/modules/connector-rbac.bicep``.
ROLE_TABLE: Final[tuple[RoleSpec, ...]] = (
    RoleSpec(
        "foundry",
        "workers",
        "Foundry User (formerly Azure AI User)",
        "53ca6127-db72-4b80-b1b0-d745d6d5456d",
        True,
        "microsoft.cognitiveservices/accounts",
        "foundry_account_ids",
    ),
    RoleSpec(
        "billing",
        "workers",
        "Storage Blob Data Reader",
        "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
        True,
        "microsoft.storage/storageaccounts",
        "billing_export_storage_account_id",
    ),
    RoleSpec(
        "gateway",
        "workers",
        "Log Analytics Data Reader",
        "3b03c2da-16b3-4a49-8834-0f8130efdd3b",
        True,
        "microsoft.operationalinsights/workspaces",
        "log_analytics_workspace_ids",
    ),
    RoleSpec(
        "gateway",
        "api",
        "API Management Service Reader Role",
        "71522526-b88f-4d52-b57f-d31fc3546d0d",
        True,
        "microsoft.apimanagement/service",
        "apim_service_ids",
    ),
    RoleSpec(
        "gateway",
        "api",
        "Monitoring Reader (diagnostic settings read)",
        UNVERIFIED,
        False,
        "microsoft.apimanagement/service",
        "apim_service_ids",
    ),
)
VERIFIED_ROLE_IDS: Final = frozenset(r.role_definition_id for r in ROLE_TABLE if r.verified)


class RefusedError(Exception):
    """A precondition failed before anything was contacted (exit 2)."""


# -- injectable edges -----------------------------------------------------------------------


@dataclass(frozen=True)
class AzResult:
    rc: int
    stdout: str = ""
    stderr: str = ""


AzRunner = Callable[[Sequence[str]], AzResult]


def default_az_runner(args: Sequence[str]) -> AzResult:  # pragma: no cover - runs a real az
    exe = shutil.which("az")
    if exe is None:
        return AzResult(127, "", "az not found")
    proc = subprocess.run([exe, *args], capture_output=True, text=True, check=False, timeout=120)
    return AzResult(proc.returncode, proc.stdout, proc.stderr)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: Any = None


HttpFn = Callable[[str, str], HttpResponse]  # (url, bearer) -> response; GET only


def default_http(url: str, bearer: str) -> HttpResponse:  # pragma: no cover - real network
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        resp = client.get(url, headers={"Authorization": f"Bearer {bearer}"})
    try:
        body = resp.json()
    except ValueError:
        body = None
    return HttpResponse(resp.status_code, body)


# -- shared guards --------------------------------------------------------------------------


def _read_registration(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RefusedError("the registration file is missing or not valid JSON") from None
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise RefusedError("the registration has an unsupported schema")
    return doc


def require_commercial(registration: Mapping[str, Any], env: Mapping[str, str]) -> None:
    """Real-tenant mode is Commercial only: refused, never bridged (PRP-139 Privacy criterion)."""
    if registration.get("cloud") != "AzureCloud":
        raise RefusedError(
            "real-tenant mode is Commercial only; the registration is not AzureCloud"
        )
    if env.get(ENV_CLOUD, "").strip().lower() in GOVERNMENT_CLOUD_NAMES:
        # Whatever ENV_DATA_MODE says: real-tenant and Government are never combined.
        raise RefusedError(f"real-tenant mode cannot be combined with {ENV_CLOUD}=government")


def require_approval(env: Mapping[str, str], what: str) -> None:
    if env.get(ENV_APPROVED) != "1":
        raise RefusedError(f"{what} needs operator approval; set {ENV_APPROVED}=1")


def require_no_credentials(env: Mapping[str, str]) -> None:
    for name in (
        "NS_COSMOS_KEY",
        "AZURE_COSMOS_KEY",
        "NS_EVENTHUBS_CONNECTION_STRING",
        "NS_BLOB_CONNECTION_STRING",
        "NS_AUTH_PSEUDONYM_KEY",
    ):
        if env.get(name):
            raise RefusedError(f"{name} is set; hosted access is Entra only")


def require_deployment(registration: Mapping[str, Any], env: Mapping[str, str]) -> None:
    deployment = registration.get("deployment_id")
    if (
        not isinstance(deployment, str)
        or not deployment
        or env.get(ENV_DEPLOYMENT_ID) != deployment
    ):
        raise RefusedError(f"{ENV_DEPLOYMENT_ID} does not match the registered deployment")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.lower().encode("utf-8")).hexdigest()[:8]


def _split_ids(raw: str | None) -> list[str]:
    seen: list[str] = []
    for part in (raw or "").split(","):
        item = part.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def parse_resource_id(resource_id: str, expected_type: str) -> tuple[str, str]:
    """(subscription id, name) of a single-resource id of ``expected_type``, else refuse."""
    match = _RESOURCE_ID_RE.fullmatch(resource_id)
    if match is None:
        raise RefusedError(
            "a scope must be the id of ONE resource (no subscription, resource group, "
            "management group or child-resource scope)"
        )
    kind = f"{match.group('ns')}/{match.group('type')}".lower()
    if kind != expected_type or GUID_RE.fullmatch(match.group("sub")) is None:
        raise RefusedError("a scope is not a resource of the type this role is planned for")
    return match.group("sub"), match.group("name")


# -- access plan ----------------------------------------------------------------------------


def _token(identity: str, role_id: str, scope: str, principal: str) -> str:
    raw = f"{identity}|{role_id}|{scope.lower()}|{principal.lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def plan_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(list(rows), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_plan(
    resources: Mapping[str, Sequence[str]], principals: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Rows of the table for the named resources. ``resources`` maps a ``RoleSpec.flag`` to ids."""
    rows: list[dict[str, Any]] = []
    for spec in ROLE_TABLE:
        for scope in resources.get(spec.flag, ()):
            parse_resource_id(scope, spec.resource_type)
            principal = principals.get(spec.identity, "")
            if GUID_RE.fullmatch(principal) is None:
                raise RefusedError(f"no {spec.identity} principal object id is known for the plan")
            rows.append(
                {
                    "row": len(rows) + 1,
                    "source": spec.source,
                    "identity": spec.identity,
                    "principal_id": principal,
                    "role_name": spec.role_name,
                    "role_definition_id": spec.role_definition_id,
                    "verified": spec.verified,
                    "scope": scope,
                    "token": _token(spec.identity, spec.role_definition_id, scope, principal)
                    if spec.verified
                    else "",
                }
            )
    return rows


def role_definition_path(sub: str, role_id: str) -> str:
    """Full role-definition id: a bare GUID fails to resolve at some scopes."""
    return f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/{role_id}"


def az_create_args(row: Mapping[str, Any]) -> list[str]:
    sub, _ = _sub_and_name(row)
    role = role_definition_path(sub, str(row["role_definition_id"]))
    return [
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        str(row["principal_id"]),
        "--assignee-principal-type",
        "ServicePrincipal",
        "--role",
        role,
        "--scope",
        str(row["scope"]),
    ]


def _sub_and_name(row: Mapping[str, Any]) -> tuple[str, str]:
    match = _RESOURCE_ID_RE.fullmatch(str(row["scope"]))
    if match is None:
        raise RefusedError("a plan row has a scope that is not a single resource id")
    return match.group("sub"), match.group("name")


def render_plan(rows: Sequence[Mapping[str, Any]], digest: str) -> str:
    lines = [f"Access plan {digest}: {len(rows)} role assignment(s). Nothing was changed.", ""]
    lines.append("row | source  | identity | role (definition id) | token | scope")
    for row in rows:
        flag = "" if row["verified"] else "  *** UNVERIFIED: cannot be applied ***"
        lines.append(
            f"{row['row']} | {row['source']} | {row['identity']} | {row['role_name']} "
            f"({row['role_definition_id']}) | {row['token'] or '-'} | {row['scope']}{flag}"
        )
    lines += ["", "Equivalent commands (Git Bash needs MSYS_NO_PATHCONV=1):"]
    for row in rows:
        if row["verified"]:
            lines.append("az " + " ".join(f'"{a}"' if "/" in a else a for a in az_create_args(row)))
        else:
            lines.append(f"# row {row['row']}: role id UNVERIFIED; no command is offered")
    return "\n".join(lines)


def cmd_access_plan(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    registration = _read_registration(args.registration)
    require_commercial(registration, env)
    principals = {
        "workers": args.workers_principal_id or str(registration.get("workers_object_id") or ""),
        "api": args.api_principal_id or str(registration.get("api_principal_id") or ""),
    }
    resources = {
        "foundry_account_ids": _split_ids(args.foundry_account_ids),
        "log_analytics_workspace_ids": _split_ids(args.log_analytics_workspace_ids),
        "apim_service_ids": _split_ids(args.apim_service_ids),
        "billing_export_storage_account_id": _split_ids(args.billing_export_storage_account_id),
    }
    if not any(resources.values()):
        raise RefusedError("name at least one resource to plan for")
    if len(resources["billing_export_storage_account_id"]) > 1:
        raise RefusedError("--billing-export-storage-account-id takes exactly one storage account")
    rows = build_plan(resources, principals)
    digest = plan_hash(rows)
    args.plan_file.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": 1, "plan_hash": digest, "created": _now().isoformat(), "rows": rows}
    args.plan_file.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_plan(rows, digest))
    print(
        f"\nPlan file written (not evidence, do not commit). Approve with --approve-plan {digest}"
    )
    return EXIT_OK


# -- access apply ---------------------------------------------------------------------------


def load_plan(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RefusedError("the plan file is missing or not valid JSON") from None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RefusedError("the plan file has no rows")
    typed = [dict(r) for r in rows if isinstance(r, dict)]
    digest = plan_hash(typed)
    if str(doc.get("plan_hash")) != digest:
        raise RefusedError("the plan file does not match its own hash; it was edited")
    return digest, typed


def _validate_row(row: Mapping[str, Any]) -> RoleSpec:
    """A row must be a verified table row with a single-resource scope of the right type."""
    spec = next(
        (
            s
            for s in ROLE_TABLE
            if s.identity == row.get("identity")
            and s.role_definition_id == row.get("role_definition_id")
        ),
        None,
    )
    if spec is None or not spec.verified or row.get("role_definition_id") not in VERIFIED_ROLE_IDS:
        raise RefusedError("a plan row names a role that is not in the verified role table")
    parse_resource_id(str(row.get("scope")), spec.resource_type)
    return spec


def _az_json(az: AzRunner, args: Sequence[str]) -> Any:
    res = az([*args, "-o", "json"])
    if res.rc != 0:
        return None
    try:
        return json.loads(res.stdout or "null")
    except ValueError:
        return None


def _reason_from(res: AzResult) -> str:
    text = f"{res.stderr}{res.stdout}".lower()
    if "authorizationfailed" in text or "does not have authorization" in text:
        return "authorization_failed"
    if "already exists" in text:
        return "already_present"
    return f"az_error_rc_{res.rc}"


def cmd_access_apply(
    args: argparse.Namespace, env: Mapping[str, str], az: AzRunner, today: str
) -> int:
    require_approval(env, "access-apply")
    registration = _read_registration(args.registration)
    require_commercial(registration, env)
    digest, rows = load_plan(args.plan_file)
    if args.approve_plan != digest:
        raise RefusedError("--approve-plan does not match the plan file hash")
    for row in rows:
        if row.get("verified"):
            _validate_row(row)
    by_token = {str(r["token"]): r for r in rows if r.get("verified") and r.get("token")}
    given = list(args.approve_assignment or [])
    for tok in given:
        if tok not in by_token:
            raise RefusedError("an --approve-assignment token is not in the plan")
    missing = [r["row"] for r in rows if r.get("verified") and str(r["token"]) not in given]
    if missing:
        raise RefusedError(f"no --approve-assignment token for plan row(s) {missing}")
    # Only now is Azure contacted: the account must be the Commercial cloud.
    cloud = az(["cloud", "show", "--query", "name", "-o", "tsv"])
    if cloud.rc != 0 or cloud.stdout.strip() != "AzureCloud":
        raise RefusedError("the az cloud is not AzureCloud; real-tenant mode is Commercial only")

    results: list[dict[str, Any]] = []
    for row in rows:
        sub, _ = _sub_and_name(row)
        entry: dict[str, Any] = {
            "row": row["row"],
            "source": row["source"],
            "identity": row["identity"],
            "role_name": row["role_name"],
            "role_definition_id": row["role_definition_id"],
            "subscription_hash": _short_hash(sub),
        }
        if not row.get("verified"):
            entry.update(outcome="skipped", reason="unverified_role")
        else:
            entry.update(_apply_row(az, row, sub))
        results.append(entry)
    evidence = {
        "gate": "hosted_real_tenant_access",
        "recorded": today,
        "plan_hash": digest,
        "rows": results,
        "counts": {
            k: sum(1 for r in results if r["outcome"] == k)
            for k in ("applied", "already_present", "skipped", "failed")
        },
    }
    path = _write_evidence(args.evidence_dir, f"{today}-access.json", evidence)
    print(json.dumps(evidence["counts"]), f"evidence: {path.name}")
    return EXIT_FAILED if evidence["counts"]["failed"] else EXIT_OK


def _apply_row(az: AzRunner, row: Mapping[str, Any], sub: str) -> dict[str, str]:
    role = role_definition_path(sub, str(row["role_definition_id"]))
    existing = _az_json(
        az,
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            str(row["principal_id"]),
            "--role",
            role,
            "--scope",
            str(row["scope"]),
        ],
    )
    if isinstance(existing, list) and existing:
        return {"outcome": "already_present", "reason": "assignment_exists"}
    res = az([*az_create_args(row), "-o", "none"])
    if res.rc == 0:
        return {"outcome": "applied", "reason": "created"}
    reason = _reason_from(res)
    if reason == "already_present":
        return {"outcome": "already_present", "reason": "assignment_exists"}
    return {"outcome": "failed", "reason": reason}


# -- bootstrap-worker -----------------------------------------------------------------------

GrantRunner = Callable[..., str]


def _default_grant_runner(  # pragma: no cover - needs the hosted Cosmos and Key Vault
    *,
    registration_path: Path,
    registration: Mapping[str, Any],
    environ: Mapping[str, str],
    tenant: str,
    customer: str,
    worker_object_id: str,
    domain_ids: Sequence[str],
) -> str:
    import asyncio

    for path in (SANDBOX_SCRIPTS, REPO):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import importlib

    from azure.identity import DefaultAzureCredential
    from neurosphere_api.runtime import AuthSettings, resolve_pseudonym_key
    from neurosphere_core.auth.jwt.config import normalize_tenant_id
    from neurosphere_core.auth.scope import PrincipalPseudonymizer
    from neurosphere_core.cloud import CloudName

    grants = importlib.import_module("sbx_grant_operator")
    require_hosted_endpoint = importlib.import_module("sbx_guard").require_hosted_endpoint

    guard: dict[str, Any] = {"registration_path": registration_path, "env": dict(environ)}
    cosmos = require_hosted_endpoint(
        f"https://{registration.get('cosmos_host')}", kind="cosmos", **guard
    )
    vault = require_hosted_endpoint(
        f"https://{registration.get('key_vault_host')}", kind="keyvault", **guard
    )
    credential = DefaultAzureCredential()
    try:
        pseudonym = grants.hosted_pseudonym_env(registration, vault, credential)
    finally:
        credential.close()
    run_env = {**environ, **pseudonym}
    saved = {name: os.environ.get(name) for name in pseudonym}
    os.environ.update(pseudonym)
    try:
        key = resolve_pseudonym_key(AuthSettings(), env=run_env.get("NS_ENV", "local"))
        principal = PrincipalPseudonymizer(key).principal_id(
            cloud=CloudName("commercial"),
            customer_id=customer,
            tenant_id=normalize_tenant_id(tenant),
            object_id=worker_object_id,
            kind="service_principal",
        )
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
    return asyncio.run(
        grants._run_hosted(  # pyright: ignore[reportPrivateUsage]
            run_env,
            cosmos,
            str(registration.get("database") or ""),
            customer_id=customer,
            principal_id=principal,
            role="viewer",
            domain_ids=tuple(domain_ids),
        )
    )


def cmd_bootstrap_worker(
    args: argparse.Namespace, env: Mapping[str, str], grant_runner: GrantRunner
) -> int:
    require_approval(env, "bootstrap-worker")
    registration = _read_registration(args.registration)
    require_commercial(registration, env)
    require_no_credentials(env)
    require_deployment(registration, env)
    if env.get("NS_ENV", "local") == "local":
        raise RefusedError("bootstrap-worker needs NS_ENV set to the hosted environment")
    customer = str(registration.get("customer_id") or "")
    if args.customer_id and args.customer_id != customer:
        raise RefusedError("--customer-id is not the registration's active customer")
    if not customer:
        raise RefusedError("the registration records no customer id")
    tenant = args.tenant_id or env.get("NS_AUTH_TENANT_ID", "")
    worker = str(registration.get("workers_object_id") or "")
    if GUID_RE.fullmatch(tenant) is None or GUID_RE.fullmatch(worker) is None:
        raise RefusedError("the tenant and the registered workers object id must be GUIDs")
    domains = _split_ids(args.domain_ids)
    if not domains:
        raise RefusedError("--domain-ids names no domain")
    for domain in domains:
        if _DOMAIN_ID_RE.fullmatch(domain) is None or domain.split(":")[1] != customer:
            raise RefusedError("a domain id is not a Commercial domain of the active customer")
    outcome = grant_runner(
        registration_path=args.registration,
        registration=registration,
        environ=env,
        tenant=tenant,
        customer=customer,
        worker_object_id=worker,
        domain_ids=domains,
    )
    print(f"worker grant {outcome}: role=viewer domains={len(domains)}")
    return EXIT_OK


# -- verify ---------------------------------------------------------------------------------

SOURCES: Final = ("foundry", "gateway", "billing", "azure_monitor")
_ALIASES: Final = {
    "foundry": "foundry",
    "azure_ai_foundry": "foundry",
    "foundry_discovery": "foundry",
    "gateway": "gateway",
    "apim_gateway": "gateway",
    "gateway_poll": "gateway",
    "billing": "billing",
    "billing_export": "billing",
    "cost": "billing",
    "azure_monitor": "azure_monitor",
    "application_insights": "azure_monitor",
    "monitor": "azure_monitor",
}
_POLL_OK: Final = frozenset({"ok", "success", "succeeded", "healthy", "complete", "completed"})
_MAX_PAGES: Final = 5
_MAX_DOMAINS: Final = 50


def _outcome(result: str, reason: str, **counts: int) -> dict[str, Any]:
    return {"result": result, "reason": reason, "counts": dict(counts)}


def _items(body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "sources"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    return []


def _read_states(body: Any) -> dict[str, str]:
    states: dict[str, str] = {}
    for item in _items(body):
        if not isinstance(item, dict):
            continue
        name = _ALIASES.get(str(item.get("source") or item.get("kind") or item.get("id") or ""))
        state = item.get("state") or item.get("status")
        if name and isinstance(state, str):
            states[name] = state
    return states


def _is_synthetic(item: Mapping[str, Any]) -> bool:
    attrs = item.get("attributes")
    if isinstance(attrs, dict) and (attrs.get("synthetic") is True):
        return True
    parts = str(item.get("id") or "").split(":")
    return (len(parts) > 2 and parts[2] == "sandbox") or item.get("source") == "sandbox"


def _decide(state: str | None, count: int, label: str, **counts: int) -> dict[str, Any]:
    if state is None:
        return _outcome("OPEN", "status_unavailable", **counts)
    if state == "not_connected":
        return _outcome("OPEN", "source_not_connected", **counts)
    if state == "failing":
        return _outcome("FAIL", "source_failing", **counts)
    if state == "connected" and count > 0:
        return _outcome("PASS", f"{label}_present", **counts)
    return _outcome("OPEN", "no_data_yet", **counts)


@dataclass
class VerifyContext:
    base: str
    bearer: str
    http: HttpFn

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> HttpResponse:
        url = f"{self.base}{path}"
        if query:
            url += "?" + urlencode(query, doseq=True)
        return self.http(url, self.bearer)


def _fetch_catalog(ctx: VerifyContext) -> tuple[list[dict[str, Any]], int, bool]:
    """Entities, last status, and whether the scan stopped with a continuation cursor pending."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    status = 200
    for _ in range(_MAX_PAGES):
        query: dict[str, Any] = {"page_size": 500}
        if cursor:
            query["cursor"] = cursor
        resp = ctx.get("/api/v1/catalog/entities", query)
        status = resp.status
        if resp.status != 200:
            return items, resp.status, False
        items.extend(i for i in _items(resp.body) if isinstance(i, dict))
        cursor = resp.body.get("next_cursor") if isinstance(resp.body, dict) else None
        if not cursor:
            break
    return items, status, bool(cursor)


def evaluate(ctx: VerifyContext, domain_ids: Sequence[str] | None) -> dict[str, Any]:
    api: dict[str, int] = {}
    status_resp = ctx.get("/api/v1/sources/status")
    api["sources_status"] = status_resp.status
    states = _read_states(status_resp.body) if status_resp.status == 200 else {}

    domains = list(domain_ids or ())
    if not domains:
        me = ctx.get("/api/v1/me/domains")
        api["me_domains"] = me.status
        if me.status == 200:
            domains = [
                str(d["domain_id"])
                for d in _items(me.body)
                if isinstance(d, dict) and d.get("domain_id")
            ]
    domains = domains[:_MAX_DOMAINS]

    entities, catalog_status, truncated = _fetch_catalog(ctx)
    api["catalog"] = catalog_status
    foundry_n = sum(
        1
        for e in entities
        if isinstance(e.get("attributes"), dict)
        and e["attributes"].get("discovered_from") == "foundry"
    )
    synthetic_n = sum(1 for e in entities if _is_synthetic(e))

    gateways = 0
    poll: dict[str, int] = {}
    billing_lines = 0
    for domain in domains:
        quoted = quote(domain, safe="")
        gw_resp = ctx.get(f"/api/v1/gateways/domains/{quoted}/gateways")
        api["gateways"] = max(api.get("gateways", 0), gw_resp.status)
        for item in _items(gw_resp.body) if gw_resp.status == 200 else []:
            if isinstance(item, dict):
                gateways += 1
                label = str(item.get("poll_status") or "none").lower()[:32]
                poll[label] = poll.get(label, 0) + 1
        rec = ctx.get(f"/api/v1/reconciliation/domains/{quoted}")
        api["reconciliation"] = max(api.get("reconciliation", 0), rec.status)
        if rec.status == 200 and isinstance(rec.body, dict):
            billing_lines += sum(
                1
                for line in rec.body.get("sources", [])
                if isinstance(line, dict) and line.get("source") == "billing"
            )

    sources: dict[str, dict[str, Any]] = {}
    if catalog_status == 200:
        sources["foundry"] = _decide(
            states.get("foundry"), foundry_n, "catalog", foundry_entities=foundry_n
        )
        if truncated and foundry_n == 0 and sources["foundry"]["result"] != "PASS":
            sources["foundry"] = _outcome("OPEN", "catalog_scan_truncated", foundry_entities=0)
    else:
        sources["foundry"] = _outcome("OPEN", "catalog_unreadable", foundry_entities=0)
    gw_counts = {"gateways": gateways, **{f"poll_{k}": v for k, v in sorted(poll.items())}}
    gw = _decide(states.get("gateway"), gateways, "gateway", **gw_counts)
    if gw["result"] == "PASS" and not any(k in _POLL_OK for k in poll):
        if any(("fail" in k or "denied" in k or "error" in k) for k in poll):
            gw = _outcome("FAIL", "poll_failed", **gw_counts)
        else:
            gw = _outcome("OPEN", "poll_pending", **gw_counts)
    sources["gateway"] = gw
    sources["billing"] = _decide(
        states.get("billing"), billing_lines, "billing", billing_lines=billing_lines
    )
    sources["azure_monitor"] = _outcome("OPEN", "follow_up_prp")
    if catalog_status == 200 and truncated and synthetic_n == 0:
        synthetic = _outcome(
            "OPEN",
            "catalog_scan_truncated",
            synthetic_records=0,
            catalog_entities=len(entities),
        )
    elif catalog_status == 200:
        synthetic = _outcome(
            "PASS" if synthetic_n == 0 else "FAIL",
            "no_synthetic_records" if synthetic_n == 0 else "synthetic_records_present",
            synthetic_records=synthetic_n,
            catalog_entities=len(entities),
        )
    else:
        synthetic = _outcome("OPEN", "catalog_unreadable", synthetic_records=0)
    return {
        "sources": sources,
        "synthetic": synthetic,
        "api_status": api,
        "catalog_truncated": truncated,
    }


def _overall(report: Mapping[str, Any]) -> str:
    results = [s["result"] for s in report["sources"].values()] + [report["synthetic"]["result"]]
    if "FAIL" in results:
        return "FAIL"
    return "OPEN" if "OPEN" in results else "PASS"


def _api_base(registration: Mapping[str, Any], host_arg: str | None) -> str:
    registered = str(registration.get("api_host") or "").strip().lower()
    host = (host_arg or registered).strip().lower()
    if not host:
        raise RefusedError("name the hosted API with --api-host (the registration records none)")
    if registered and host != registered:
        raise RefusedError("--api-host is not the registered deployment's API host")
    if _HOST_RE.fullmatch(host) is None or "." not in host or host == "localhost":
        raise RefusedError("the API host must be a hosted DNS name, never a local address")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RefusedError("the API host must be a DNS name, not an IP address")
    return f"https://{host}"


def cmd_verify(
    args: argparse.Namespace,
    env: Mapping[str, str],
    az: AzRunner,
    http: HttpFn,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    today: str,
) -> int:
    require_approval(env, "verify")
    registration = _read_registration(args.registration)
    require_commercial(registration, env)
    require_no_credentials(env)
    require_deployment(registration, env)
    base = _api_base(registration, args.api_host)
    audience = args.api_audience or str(registration.get("api_audience") or "")
    if not audience:
        raise RefusedError("name the API token audience with --api-audience")
    cloud = az(["cloud", "show", "--query", "name", "-o", "tsv"])
    if cloud.rc != 0 or cloud.stdout.strip() != "AzureCloud":
        raise RefusedError("the az cloud is not AzureCloud; real-tenant mode is Commercial only")
    tok = az(
        [
            "account",
            "get-access-token",
            "--resource",
            audience,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ]
    )
    bearer = tok.stdout.strip() if tok.rc == 0 else ""
    if not bearer:
        raise RefusedError("could not get an operator token from az (sign in with az login)")

    ctx = VerifyContext(base=base, bearer=bearer, http=http)
    domains = _split_ids(args.domain_ids) or None
    started = clock()
    waited = 0.0
    report = evaluate(ctx, domains)
    while (
        any(s["reason"] == "source_failing" for s in report["sources"].values())
        and clock() - started + args.retry_interval_seconds <= args.propagation_seconds
    ):
        sleep(args.retry_interval_seconds)
        waited = clock() - started
        report = evaluate(ctx, domains)
    overall = _overall(report)
    doc = {
        "gate": "hosted_real_tenant_verify",
        "recorded": today,
        "cloud": "AzureCloud",
        "data_mode": str(registration.get("data_mode") or "demo"),
        "overall": overall,
        "propagation_waited_seconds": int(waited),
        "sources": report["sources"],
        "synthetic": report["synthetic"],
        "api_status": report["api_status"],
        "catalog_truncated": report["catalog_truncated"],
    }
    path = _write_evidence(args.evidence_dir, f"{today}-verify.json", doc)
    for name, entry in report["sources"].items():
        print(f"{name}: {entry['result']} ({entry['reason']})")
    print(f"synthetic: {report['synthetic']['result']} ({report['synthetic']['reason']})")
    print(f"overall: {overall}; evidence: {path.name}")
    return EXIT_FAILED if overall == "FAIL" else EXIT_OK


# -- plumbing -------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _write_evidence(evidence_dir: Path, name: str, doc: Mapping[str, Any]) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / name
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hosted real-tenant access, bootstrap, verify.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)

    plan = sub.add_parser(
        "access-plan", help="print and write the role assignments; changes nothing"
    )
    common(plan)
    plan.add_argument("--foundry-account-ids", help="comma-separated Foundry account resource ids")
    plan.add_argument("--log-analytics-workspace-ids", help="comma-separated workspace ids")
    plan.add_argument("--apim-service-ids", help="comma-separated API Management service ids")
    plan.add_argument("--billing-export-storage-account-id", help="the export storage account id")
    plan.add_argument("--workers-principal-id", help="default: registration workers_object_id")
    plan.add_argument("--api-principal-id", help="default: registration api_principal_id")
    plan.add_argument("--plan-file", type=Path, default=DEFAULT_PLAN_FILE)

    apply_ = sub.add_parser("access-apply", help="apply the approved rows (NS_LIVE_APPROVED=1)")
    common(apply_)
    apply_.add_argument("--plan-file", type=Path, default=DEFAULT_PLAN_FILE)
    apply_.add_argument("--approve-plan", required=True, help="the plan hash access-plan printed")
    apply_.add_argument(
        "--approve-assignment", action="append", default=[], help="one token per plan row"
    )
    apply_.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)

    boot = sub.add_parser("bootstrap-worker", help="grant the workers principal viewer on domains")
    common(boot)
    boot.add_argument("--domain-ids", required=True, help="comma-separated canonical domain ids")
    boot.add_argument("--tenant-id", help="default: NS_AUTH_TENANT_ID")
    boot.add_argument("--customer-id", help="must equal the registration's customer id")

    ver = sub.add_parser("verify", help="per-source PASS/FAIL/OPEN through the hosted API")
    common(ver)
    ver.add_argument("--api-host", help="default: registration api_host")
    ver.add_argument("--api-audience", help="token resource for az (default: registration)")
    ver.add_argument("--domain-ids", help="comma-separated; default: the operator's domains")
    ver.add_argument("--propagation-seconds", type=int, default=DEFAULT_PROPAGATION_SECONDS)
    ver.add_argument("--retry-interval-seconds", type=int, default=DEFAULT_RETRY_INTERVAL_SECONDS)
    ver.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    az_runner: AzRunner | None = None,
    http: HttpFn | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    grant_runner: GrantRunner | None = None,
    today: str | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)
    day = today or _now().strftime("%Y-%m-%d")
    try:
        if args.command == "access-plan":
            return cmd_access_plan(args, environ)
        if args.command == "access-apply":
            return cmd_access_apply(args, environ, az_runner or default_az_runner, day)
        if args.command == "bootstrap-worker":
            return cmd_bootstrap_worker(args, environ, grant_runner or _default_grant_runner)
        return cmd_verify(
            args,
            environ,
            az_runner or default_az_runner,
            http or default_http,
            sleep or time.sleep,
            clock or time.monotonic,
            day,
        )
    except RefusedError as exc:
        print(f"REFUSED: {exc}. Nothing was changed.", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
