"""Shared helpers for ``hosted_demo.py`` (PRP-32 item 4): no ``az`` call is made from here.

Pure pieces only: constants, the D9 parameter file, the what-if change hash, the evidence
writer, the ownership-register book and the pseudonym secret handling. g01 helpers
(``scrub``, ``redact_subscriptions``, the runner types) are imported through ``importlib`` so
that g01 stays untouched.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parents[2]
TEMPLATE: Final = "infra/demo/main.bicep"
DEPLOYMENT_NAME: Final = "hosted-demo"
GATE: Final = "PRP-32"
SCRIPT_VERSION: Final = "1.0.0"
DEFAULT_RG: Final = "rg-neurosphere-demo"
DEFAULT_LOCATION: Final = "centralus"
EVIDENCE_DIR: Final = REPO / "docs" / "evidence" / "PRP-32"
STATE_DIR: Final = REPO / "temp" / "hosted-demo"
REGISTER_CONTAINER: Final = "deploy_register"

SHARED_TOKENS: Final = ("hub-subnet", "hub-pe", "hub-dns", "foundry-role", "entra-app", "budget")
DEPLOY_SHARED: Final = ("hub-subnet", "hub-pe", "hub-dns", "budget")

OPENAI_USER_ROLE: Final = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
COSMOS_DATA_CONTRIBUTOR: Final = "00000000-0000-0000-0000-000000000002"
EVENTHUBS_SENDER_ROLE: Final = "2b629674-e913-4c01-ae53-ef4638d8f975"
BLOB_CONTRIBUTOR_ROLE: Final = "ba92f5b4-2d11-453d-a403-e96b7ff2f5be"
KEYVAULT_SECRETS_USER_ROLE: Final = "4633458b-17de-40ec-b70d-d39de3fe5b0a"

HUB_ZONES: Final = {
    "cosmosDnsZoneId": "privatelink.documents.azure.com",
    "eventHubsDnsZoneId": "privatelink.servicebus.windows.net",
    "blobDnsZoneId": "privatelink.blob.core.windows.net",
    "webAppsDnsZoneId": "privatelink.azurewebsites.net",
    "keyVaultDnsZoneId": "privatelink.vaultcore.azure.net",
}

#: Parameter names generated for ``infra/demo/main.bicep`` (D9). Checked against the template.
GENERATED_PARAMS: Final = (
    "prefix",
    "location",
    "imageRegistry",
    "imageTag",
    "appServiceSkuName",
    "deployKeyVault",
    "integrationSubnetId",
    "privateEndpointSubnetId",
    "cosmosDnsZoneId",
    "eventHubsDnsZoneId",
    "blobDnsZoneId",
    "webAppsDnsZoneId",
    "keyVaultDnsZoneId",
    "entraTenantId",
    "entraClientId",
    "copilotEndpoint",
    "copilotDeployment",
    "budgetAmount",
    "budgetStartDate",
    "budgetContactEmails",
    "tagOwner",
    "tagDeleteAfter",
    "deploymentId",
    "createdBy",
)

OPERATOR_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
GUID_RE: Final = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")

AzCall = Callable[[Sequence[str]], Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _gates_on_path() -> None:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


def g01() -> Any:
    """The g01 helper module (scrub, redact_subscriptions, AzResult, SubprocessAzRunner)."""
    _gates_on_path()
    return importlib.import_module("g01_deploy_smoke")


def p29() -> Any:
    """p29_entra_local, for ``az_command`` (bypasses az.cmd, which mangles Graph URLs)."""
    _gates_on_path()
    return importlib.import_module("p29_entra_local")


# --------------------------------------------------------------------------- ids and params


def parse_arm_id(resource_id: str) -> dict[str, str]:
    """Subscription, resource group, provider, and the last type/name of an ARM id."""
    parts = resource_id.strip("/").split("/")
    low = [p.lower() for p in parts]
    out: dict[str, str] = {"name": parts[-1] if parts else ""}
    if "subscriptions" in low:
        out["subscription"] = parts[low.index("subscriptions") + 1]
    if "resourcegroups" in low:
        out["resource_group"] = parts[low.index("resourcegroups") + 1]
    return out


def resource_type(resource_id: str) -> str:
    return g01().resource_type_from_id(resource_id).lower()


def build_parameters(values: Mapping[str, Any]) -> dict[str, Any]:
    """ARM deployment-parameters document from ``{name: value}``."""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {k: {"value": v} for k, v in values.items()},
    }


def default_delete_after(today: date | None = None) -> str:
    return ((today or utcnow().date()) + timedelta(days=30)).isoformat()


def default_budget_start(today: date | None = None) -> str:
    return (today or utcnow().date()).replace(day=1).isoformat()


def normalize_changes(what_if: Any) -> list[dict[str, str]]:
    """Stable, sorted change list from a ``what-if`` result (``Ignore`` entries dropped)."""
    raw = what_if.get("changes", []) if isinstance(what_if, dict) else []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("changeType", "Unknown"))
        if kind == "Ignore":
            continue
        rid = str(item.get("resourceId", "")).rstrip("/").lower()
        out.append({"changeType": kind, "resourceId": rid, "resourceType": resource_type(rid)})
    return sorted(out, key=lambda c: (c["resourceId"], c["changeType"]))


def changes_hash(changes: Sequence[Mapping[str, str]]) -> str:
    blob = json.dumps(list(changes), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def summarize_changes(changes: Sequence[Mapping[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in changes:
        counts[c["changeType"]] = counts.get(c["changeType"], 0) + 1
    return counts


def bind_hash(changes_digest: str, shared: Mapping[str, str]) -> str:
    """Plan hash bound to the shared-resource parameters (normalized, lowercased values).

    Swapping a subnet, DNS zone, Foundry account or Entra client between ``plan`` and ``deploy``
    changes this hash even when the what-if change list is identical.
    """
    material = {k: str(v).strip().lower() for k, v in sorted(shared.items())}
    blob = json.dumps(
        {"changes": changes_digest, "shared": material}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_ARM_SEGMENT = r"[A-Za-z0-9_.()-]+"
ARM_ID_RE: Final = re.compile(
    rf"/subscriptions/{GUID_RE.pattern}/resourceGroups/{_ARM_SEGMENT}"
    rf"/providers/{_ARM_SEGMENT}(?:/{_ARM_SEGMENT})+",
    re.IGNORECASE,
)


def is_guid(value: str) -> bool:
    return GUID_RE.fullmatch(value) is not None


def is_arm_id(value: str) -> bool:
    """A subscription-scoped ARM resource id with plain path segments (no ``..``, no query)."""
    if ARM_ID_RE.fullmatch(value) is None:
        return False
    return not any(seg in (".", "..") for seg in value.split("/"))


def parse_shared(value: str) -> list[str]:
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    unknown = [t for t in tokens if t not in SHARED_TOKENS]
    if unknown:
        raise ValueError(f"unknown --approve-shared token(s): {', '.join(sorted(unknown))}")
    return tokens


# --------------------------------------------------------------------------- evidence


def redact_guids(value: Any) -> Any:
    """Replace every GUID in any string with ``<guid:sha8>`` (the repository is public)."""
    if isinstance(value, dict):
        return {k: redact_guids(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [redact_guids(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str):

        def token(m: re.Match[str]) -> str:
            digest = hashlib.sha256(m.group(0).lower().encode("utf-8")).hexdigest()
            return f"<guid:{digest[:8]}>"

        return GUID_RE.sub(token, value)
    return value


def finalize_evidence(evidence: dict[str, Any], subscription: str) -> dict[str, Any]:
    """Scrub (raises ``ScrubError``), then redact subscription ids and all other GUIDs."""
    mod = g01()
    mod.scrub(evidence)
    redacted = mod.redact_subscriptions(evidence, [subscription])
    return redact_guids(redacted)


def markdown(ev: Mapping[str, Any]) -> str:
    lines = [
        f"# PRP-32 hosted demo: {ev.get('command')} - {ev.get('result')}",
        "",
        f"- Window (UTC): {ev.get('started_utc')} to {ev.get('finished_utc')}",
        f"- Operator: {ev.get('operator')}",
        f"- Resource group: {ev.get('resource_group')} ({ev.get('location')})",
        "",
        "## Approvals",
        "",
    ]
    lines += [
        f"- {a['token']} by {a['operator']} at {a['utc']}" for a in ev.get("approvals", [])
    ] or ["- none"]
    lines += ["", "## Steps", ""]
    lines += [f"- [{s['status']}] {s['step']} {s.get('detail', '')}".rstrip() for s in ev["steps"]]
    if ev.get("errors"):
        lines += ["", "## Errors", ""] + [f"- {e}" for e in ev["errors"]]
    return "\n".join(lines) + "\n"


def write_evidence(evidence: dict[str, Any], evidence_dir: Path, command: str) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow()
    path = evidence_dir / f"{stamp:%Y-%m-%d}-{command}.json"
    if path.exists():
        path = evidence_dir / f"{stamp:%Y-%m-%d}-{stamp:%H%M%S}-{command}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(markdown(evidence), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- pseudonym secret


def new_pseudonym_value() -> str:
    """A fresh pseudonym key (D4). Never printed, logged, or put on a command line."""
    return secrets.token_urlsafe(48)


def write_secret_file(work_dir: Path, value: str) -> Path:
    """Write ``value`` to a 0600 temp file (mkstemp creates it owner-only where supported)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="kv-", suffix=".txt", dir=work_dir)
    try:
        os.write(fd, value.encode("utf-8"))
    finally:
        os.close(fd)
    return Path(name)


# --------------------------------------------------------------------------- register book


class RegisterBook:
    """The ownership register: a local JSON export plus an optional Cosmos backend.

    ``backend`` exposes ``put_rows(rows)`` and ``list_rows(deployment_id)`` (both sync); the
    real one wraps ``CosmosRegisterStore`` over Entra. Teardown reads either copy.
    """

    def __init__(self, deployment_id: str, state_dir: Path, backend: Any | None) -> None:
        self.deployment_id = deployment_id
        self.state_dir = state_dir
        self.backend = backend
        self.rows: list[Any] = []

    @property
    def path(self) -> Path:
        return self.state_dir / f"register-{self.deployment_id}.json"

    def load(self) -> bool:
        """Load rows from the local copy, else the Cosmos copy. False if neither is readable."""
        from neurosphere_core.deploy.register import RegisterExport

        try:
            export = RegisterExport.model_validate_json(self.path.read_text(encoding="utf-8"))
            self.rows = list(export.rows)
            return True
        except (OSError, ValueError):
            pass
        if self.backend is not None:
            try:
                self.rows = list(self.backend.list_rows(self.deployment_id))
            except Exception:
                return False
            return bool(self.rows)
        return False

    def add(self, rows: Iterable[Any]) -> None:
        by_id = {r.resource_id.lower(): r for r in self.rows}
        for r in rows:
            by_id[r.resource_id.lower()] = r
        self.rows = list(by_id.values())

    def remove(self, resource_ids: Iterable[str]) -> int:
        """Drop rows by resource id (case-insensitive); returns how many were dropped."""
        gone = {i.lower() for i in resource_ids}
        kept = [r for r in self.rows if r.resource_id.lower() not in gone]
        dropped = len(self.rows) - len(kept)
        self.rows = kept
        return dropped

    def save(self) -> list[str]:
        """Write both copies; returns problems (a Cosmos failure is reported, never hidden)."""
        from neurosphere_core.deploy.register import RegisterExport

        problems: list[str] = []
        self.state_dir.mkdir(parents=True, exist_ok=True)
        export = RegisterExport(deployment_id=self.deployment_id, rows=tuple(self.rows))
        self.path.write_text(export.model_dump_json(indent=2), encoding="utf-8")
        if self.backend is None:
            problems.append("no Cosmos register backend; only the local register copy was written")
        else:
            try:
                self.backend.put_rows(self.rows)
            except Exception as exc:
                problems.append(f"Cosmos register write failed ({type(exc).__name__})")
        return problems
