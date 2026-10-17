"""G01 live run: Commercial deploy smoke for the PRP-08 Bicep modules.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before argument
parsing, any import of project code, or any `az` invocation). This deploys BILLABLE Azure
resources into a resource group that this script creates, checks health, writes an evidence
manifest and tears down only what it created.

Preconditions (operator): `az` is installed and signed in to the Commercial cloud
(`AzureCloud`) with the target subscription active. The script never logs in, never reads
tokens or keys, and never calls `listKeys`.

Evidence: docs/evidence/G01/<UTC date>-commercial-deploy-smoke.{json,md}. The evidence dict is
built only from whitelisted fields (ids, types, provisioning states, counts) and is passed
through a secret scrubber that fails the run if any value looks like a credential.

Exit codes: 0 PASS, 1 FAIL (deployment or teardown problem, evidence written), 2 REFUSED
(approval, cloud, subscription, region or resource-group precondition; nothing changed).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = Path(__file__).resolve().parents[2]
SCRIPT_VERSION = "1.0.0"
GATE = "G01"
TEMPLATE = "infra/bicep/modules/main.bicep"
PARAMS = "infra/bicep/params/commercial/main.bicepparam"
DEFAULT_LOCATION = "eastus2"
CONSENT_REFERENCE = "operator-g01-smoke"
TAGS = ("neurosphere:created-by=neurosphere", "neurosphere:gate=G01")
AZ_TIMEOUT_SECONDS = 3 * 60 * 60  # APIM Developer takes ~30-45 min; leave headroom.

_GOV_PREFIXES = ("usgov", "usdod")
_KEYVAULT = "microsoft.keyvault/vaults"
_APIM = "microsoft.apimanagement/service"


# --------------------------------------------------------------------------- az runner


class AzResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


class AzRunner(Protocol):
    """Runs one `az` invocation (arguments exclude the `az` executable itself)."""

    def __call__(self, args: Sequence[str]) -> AzResult: ...


class SubprocessAzRunner:
    """The real runner: resolved `az`, list args, no shell."""

    def __init__(self, az_path: str) -> None:
        self._az = az_path

    def __call__(self, args: Sequence[str]) -> AzResult:
        proc = subprocess.run(
            [self._az, *args],
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


class AzError(RuntimeError):
    pass


class RefusedError(RuntimeError):
    """A precondition failed before anything was changed."""


# --------------------------------------------------------------------------- scrubber

_SECRET_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}"),  # JWT header
    re.compile(r"AccountKey\s*=", re.IGNORECASE),
    re.compile(r"SharedAccessKey(Name)?\s*=", re.IGNORECASE),
    re.compile(r"DefaultEndpointsProtocol\s*=", re.IGNORECASE),
    re.compile(r"-----BEGIN"),
    re.compile(r"[A-Za-z0-9+/]{40,}={1,2}"),  # long base64 with padding
    re.compile(r"(?i)\b(password|passwd|secret|api[-_]?key|bearer)\b\s*[:=]\s*\S"),
    re.compile(r"(?i)[?&]sig=[A-Za-z0-9%+/=]{8,}"),
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(access.?token|primary.?key|secondary.?key|connection.?string|list.?keys"
    r"|password|secret|sas.?token|api.?key)"
)


class ScrubError(RuntimeError):
    pass


def _looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_VALUE_PATTERNS)


def scrub(value: Any, path: str = "$") -> None:
    """Raise ``ScrubError`` if any key or string value in ``value`` looks like a credential."""
    if isinstance(value, dict):
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            k = str(key)  # pyright: ignore[reportUnknownArgumentType]
            if _SECRET_KEY_PATTERN.search(k) or _looks_secret(k):
                raise ScrubError(f"secret-like key at {path}.{k}")
            scrub(item, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            scrub(item, f"{path}[{i}]")
    elif isinstance(value, str) and _looks_secret(value):
        raise ScrubError(f"secret-like value at {path}")


_SUBSCRIPTION_IN_ID = re.compile(r"/subscriptions/([0-9a-fA-F-]{36})", re.IGNORECASE)
SUBSCRIPTION_REDACTION_NOTE = (
    "subscription ids replaced with <subscription:sha256-8> (first 8 hex of the SHA-256 of the "
    "lowercase id); the repository is public"
)


def subscription_token(subscription_id: str) -> str:
    digest = hashlib.sha256(subscription_id.strip().lower().encode("utf-8")).hexdigest()
    return f"<subscription:{digest[:8]}>"


def _collect_subscriptions(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():  # pyright: ignore[reportUnknownVariableType]
            _collect_subscriptions(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            _collect_subscriptions(item, found)
    elif isinstance(value, str):
        found.update(m.lower() for m in _SUBSCRIPTION_IN_ID.findall(value))


def _replace_ids(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _replace_ids(v, tokens) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_replace_ids(v, tokens) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str):
        out = value
        for sub, token in tokens.items():
            out = re.sub(re.escape(sub), token, out, flags=re.IGNORECASE)
        return out
    return value


def redact_subscriptions(evidence: dict[str, Any], extra: Sequence[str] = ()) -> dict[str, Any]:
    """Replace every subscription id (in ARM ids and the given ``extra`` ids) with a token."""
    found: set[str] = {s.strip().lower() for s in extra if s}
    _collect_subscriptions(evidence, found)
    redacted = _replace_ids(evidence, {s: subscription_token(s) for s in found})
    notes = list(redacted.get("redactions") or [])
    if SUBSCRIPTION_REDACTION_NOTE not in notes:
        notes.append(SUBSCRIPTION_REDACTION_NOTE)
    redacted["redactions"] = notes
    return redacted


def safe_text(text: str, limit: int = 300) -> str:
    """Truncate az error text; redact it entirely if it matches a secret pattern."""
    cleaned = " ".join(text.split())[:limit]
    return "[redacted: matched a secret pattern]" if _looks_secret(cleaned) else cleaned


# --------------------------------------------------------------------------- helpers


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(resource_id: str) -> str:
    return resource_id.rstrip("/").lower()


def resource_type_from_id(resource_id: str) -> str:
    """`/subscriptions/s/resourceGroups/g/providers/A.B/t/n/c/m` -> `A.B/t/c`."""
    parts = resource_id.strip("/").split("/")
    lowered = [p.lower() for p in parts]
    if "providers" not in lowered:
        return "unknown"
    rest = parts[lowered.index("providers") + 1 :]
    if len(rest) < 3:
        return rest[0] if rest else "unknown"
    types = [rest[0] + "/" + rest[1], *rest[3::2]]
    return "/".join([types[0], *types[1:]])


def default_location() -> str:
    try:
        text = (REPO / PARAMS).read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_LOCATION
    found = re.search(r"^\s*param\s+location\s*=\s*'([^']+)'", text, re.MULTILINE)
    return found.group(1) if found else DEFAULT_LOCATION


def is_government_location(location: str) -> bool:
    return location.strip().lower().startswith(_GOV_PREFIXES)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="G01 Commercial deploy smoke (operator-approved).")
    ap.add_argument("--subscription", required=True, help="Commercial subscription id (guid)")
    ap.add_argument("--resource-group", required=True, help="NEW resource group; must not exist")
    ap.add_argument("--location", default=default_location(), help="Commercial region")
    ap.add_argument("--reuse-apim", default="", help="ARM id of an existing APIM to reuse")
    ap.add_argument("--apim-publisher-email", default="", help="required when creating APIM")
    ap.add_argument("--apim-publisher-name", default="", help="required when creating APIM")
    ap.add_argument("--keep", action="store_true", help="skip teardown (default: tear down)")
    ap.add_argument("--evidence-dir", default=str(REPO / "docs" / "evidence" / "G01"))
    return ap


# --------------------------------------------------------------------------- the smoke


@dataclass
class Smoke:
    run_az: AzRunner
    subscription: str
    resource_group: str
    location: str
    reuse_apim: str
    publisher_email: str
    publisher_name: str
    keep: bool
    work_dir: Path
    steps: list[dict[str, Any]] = field(default_factory=lambda: [])
    rg_created: bool = False

    # ---- az plumbing

    def az(self, *args: str, parse: bool = True) -> Any:
        res = self.run_az(args)
        if res.rc != 0:
            raise AzError(f"az {' '.join(args[:3])} failed: {safe_text(res.stderr)}")
        if not parse:
            return None
        text = res.stdout.strip()
        return json.loads(text) if text else None

    @property
    def rg_id(self) -> str:
        return f"/subscriptions/{self.subscription}/resourceGroups/{self.resource_group}"

    def step(self, name: str, status: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {"step": name, "status": status, "detail": detail, **extra}
        self.steps.append(entry)
        print(f"[{status}] {name} {detail}".rstrip())
        return entry

    # ---- preflight (no changes)

    def preflight(self) -> None:
        cloud = self.az("cloud", "show", "--query", "name", "--output", "json")
        if cloud != "AzureCloud":
            raise RefusedError(f"active az cloud is {cloud!r}; G01 is Commercial only (AzureCloud)")
        active = self.az("account", "show", "--query", "id", "--output", "json")
        if str(active).lower() != self.subscription.lower():
            raise RefusedError("active az subscription does not match --subscription")
        exists = self.az(
            "group",
            "exists",
            "--name",
            self.resource_group,
            "--subscription",
            self.subscription,
            "--output",
            "json",
        )
        if exists is not False:
            raise RefusedError(
                f"resource group {self.resource_group!r} already exists (or could not be "
                "confirmed absent); G01 only deploys into a group it creates. No changes made."
            )

    # ---- deploy

    def _parameters_file(self) -> Path:
        built = self.az("bicep", "build-params", "--file", PARAMS, "--stdout")
        if isinstance(built, dict) and "parametersJson" in built:
            built = json.loads(built["parametersJson"])
        if not isinstance(built, dict) or not isinstance(built.get("parameters"), dict):
            raise AzError("az bicep build-params returned no parameters object")
        params: dict[str, Any] = built["parameters"]
        params["location"] = {"value": self.location}
        if self.reuse_apim:
            params["reuseApim"] = {"value": self.reuse_apim}
        else:
            params["apimPublisherEmail"] = {"value": self.publisher_email}
            params["apimPublisherName"] = {"value": self.publisher_name}
        self.work_dir.mkdir(parents=True, exist_ok=True)
        path = self.work_dir / f"g01-params-{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(built), encoding="utf-8")
        return path

    def create_resource_group(self) -> None:
        self.az(
            "group",
            "create",
            "--name",
            self.resource_group,
            "--location",
            self.location,
            "--subscription",
            self.subscription,
            "--tags",
            *TAGS,
            "--output",
            "json",
        )
        self.rg_created = True
        self.step("resource-group-create", "ok", self.resource_group)

    def what_if(self, params_arg: str) -> dict[str, Any]:
        out = self.az(*self._deploy_args("what-if", params_arg), "--no-pretty-print")
        raw = out.get("changes", []) if isinstance(out, dict) else []
        changes: list[dict[str, str]] = []
        counts: dict[str, int] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("resourceId", ""))
            kind = str(item.get("changeType", "Unknown"))
            counts[kind] = counts.get(kind, 0) + 1
            changes.append(
                {"changeType": kind, "resourceId": rid, "resourceType": resource_type_from_id(rid)}
            )
        summary: dict[str, Any] = {"counts_by_change_type": counts, "changes": changes}
        self.step("what-if", "ok", f"{len(changes)} change(s)")
        return summary

    def _deploy_args(self, verb: str, params_arg: str) -> list[str]:
        return [
            "deployment",
            "group",
            verb,
            "--resource-group",
            self.resource_group,
            "--subscription",
            self.subscription,
            "--name",
            "g01-smoke",
            "--template-file",
            TEMPLATE,
            "--parameters",
            params_arg,
            "--output",
            "json",
        ]

    def deploy(self, params_arg: str) -> dict[str, Any]:
        out = self.az(*self._deploy_args("create", params_arg))
        props = out.get("properties", {}) if isinstance(out, dict) else {}
        state = str(props.get("provisioningState", "Unknown"))
        outputs: dict[str, str] = {}
        for name, body in (props.get("outputs") or {}).items():
            value = body.get("value") if isinstance(body, dict) else None
            if isinstance(value, str) and value.lower().startswith("/subscriptions/"):
                outputs[str(name)] = value  # resource ids only; never other output values
        self.step("deployment-create", "ok" if state == "Succeeded" else "failed", state)
        return {"provisioningState": state, "output_resource_ids": outputs}

    def list_resources(self) -> list[dict[str, str]]:
        out = self.az(
            "resource",
            "list",
            "--resource-group",
            self.resource_group,
            "--subscription",
            self.subscription,
            "--output",
            "json",
        )
        found: list[dict[str, str]] = []
        for item in out or []:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id", ""))
            state = item.get("provisioningState")
            if not state and rid:
                state = self.az(
                    "resource",
                    "show",
                    "--ids",
                    rid,
                    "--query",
                    "properties.provisioningState",
                    "--output",
                    "json",
                )
            found.append(
                {
                    "id": rid,
                    "type": str(item.get("type") or resource_type_from_id(rid)),
                    "name": str(item.get("name") or rid.rsplit("/", 1)[-1]),
                    "location": str(item.get("location") or self.location),
                    "provisioningState": str(state or "Unknown"),
                }
            )
        return found

    @staticmethod
    def health(resources: list[dict[str, str]], deployment_state: str) -> dict[str, Any]:
        bad = [r["id"] for r in resources if r["provisioningState"] != "Succeeded"]
        ok = bool(resources) and not bad and deployment_state == "Succeeded"
        return {
            "ok": ok,
            "deployment_provisioning_state": deployment_state,
            "resource_count": len(resources),
            "not_succeeded": bad,
        }

    # ---- teardown

    def teardown(self, snapshot: list[dict[str, str]] | None) -> dict[str, Any]:
        result: dict[str, Any] = {"performed": False, "ok": False, "steps": [], "purge": {}}
        start = len(self.steps)
        try:
            self._teardown(snapshot, result)
        except (RefusedError, AzError, ScrubError) as exc:
            self.step("teardown", "failed", safe_text(str(exc)))
            result["ok"] = False
        result["steps"] = self.steps[start:]
        return result

    def _teardown(self, snapshot: list[dict[str, str]] | None, result: dict[str, Any]) -> None:
        # Imported here so the refusal path and `--help` never need project code.
        from neurosphere_core.deploy.register import (
            Action,
            InMemoryRegisterStore,
            Ownership,
            ResourceRow,
            plan_removal,
        )

        known = snapshot if snapshot is not None else self.list_resources()
        live = self.list_resources()
        deployment_id = "g01-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", self.resource_group)[:100]
        now = _utcnow()

        def row(rid: str, service: str, *, reused: bool) -> ResourceRow:
            return ResourceRow(
                deployment_id=deployment_id,
                resource_id=rid,
                service=service[:64],
                ownership=Ownership.REUSED if reused else Ownership.CREATED,
                created_by=None if reused else "neurosphere",
                owner="g01-smoke-operator",
                consent_reference=CONSENT_REFERENCE if reused else None,
                creating_plan_id="g01-smoke",
                recorded_at=now,
            )

        rows = [row(self.rg_id, "Microsoft.Resources/resourceGroups", reused=False)]
        reuse_key = _norm(self.reuse_apim) if self.reuse_apim else ""
        for res in known:
            if _norm(res["id"]) == reuse_key:
                continue
            rows.append(row(res["id"], res["type"], reused=False))
        if self.reuse_apim:
            rows.append(row(self.reuse_apim, "Microsoft.ApiManagement/service", reused=True))

        registered = {_norm(r.resource_id): r for r in rows}
        foreign = [r["id"] for r in live if _norm(r["id"]) not in registered]
        not_ours = [
            r["id"]
            for r in live
            if _norm(r["id"]) in registered
            and registered[_norm(r["id"])].ownership is not Ownership.CREATED
        ]
        if foreign or not_ours:
            raise RefusedError(
                "resource group contains resources NeuroSphere did not create "
                f"({len(foreign) + len(not_ours)}); refusing to delete it. Left in place: "
                f"{self.resource_group}"
            )

        store = InMemoryRegisterStore()
        stored = asyncio.run(self._fill(store, rows, deployment_id))
        plan = plan_removal(deployment_id, stored, unregistered_ids=[r["id"] for r in live])
        expected = {_norm(r.resource_id) for r in stored if r.ownership is Ownership.CREATED}
        removable = {_norm(e.resource_id) for e in plan.removable}
        if removable != expected:
            raise RefusedError(
                "removal plan does not match the expected created rows; nothing deleted"
            )
        if self.reuse_apim:
            reused_entries = [e for e in plan.entries if _norm(e.resource_id) == reuse_key]
            if not reused_entries or any(e.action is not Action.UNTOUCHED for e in reused_entries):
                raise RefusedError(
                    "reused APIM is not untouched in the removal plan; nothing deleted"
                )
        self.step("removal-plan", "ok", f"{len(removable)} removable, reused untouched")
        result["performed"] = True

        purge_targets = [
            r for r in known if _norm(r["id"]) in expected and _norm(r["id"]) != reuse_key
        ]
        self.az(
            "group",
            "delete",
            "--name",
            self.resource_group,
            "--subscription",
            self.subscription,
            "--yes",
            parse=False,
        )
        self.step("resource-group-delete", "ok", self.resource_group)

        purge: dict[str, str] = {}
        for res in purge_targets:
            rtype = res["type"].lower()
            if rtype == _KEYVAULT:
                cmd = ["keyvault", "purge", "--name", res["name"]]
                label = f"keyvault-purge:{res['name']}"
            elif rtype == _APIM:
                cmd = ["apim", "deletedservice", "purge", "--service-name", res["name"]]
                label = f"apim-purge:{res['name']}"
            else:
                continue
            res_in = self.run_az(
                [*cmd, "--location", res["location"], "--subscription", self.subscription]
            )
            if res_in.rc == 0:
                purge[label] = "purged"
                self.step(label, "ok", "purged")
            elif "purge protection" in res_in.stderr.lower() or (
                rtype == _KEYVAULT and self._kv_purge_protected(res["name"], res["location"])
            ):
                # keyvault.bicep sets enablePurgeProtection=true: the vault stays soft-deleted
                # until its retention elapses. Recorded explicitly, not hidden.
                purge[label] = "blocked_by_purge_protection"
                self.step(label, "warning", "blocked by purge protection (retention applies)")
            else:
                purge[label] = "failed"
                self.step(label, "failed", safe_text(res_in.stderr))
        result["purge"] = purge
        result["ok"] = all(v != "failed" for v in purge.values())

    def _kv_purge_protected(self, name: str, location: str) -> bool:
        # Azure answers a purge-protected vault with "MethodNotAllowed: Operation
        # 'DeletedVaultPurge' is not allowed" (observed 2026-10-17), which names no protection.
        # Ask the soft-deleted vault itself instead of parsing the error text.
        res = self.run_az(
            [
                "keyvault",
                "show-deleted",
                "--name",
                name,
                "--location",
                location,
                "--subscription",
                self.subscription,
            ]
        )
        if res.rc != 0 or not res.stdout.strip():
            return False
        try:
            body = json.loads(res.stdout)
        except json.JSONDecodeError:
            return False
        return (body.get("properties") or {}).get("purgeProtectionEnabled") is True

    @staticmethod
    async def _fill(store: Any, rows: list[Any], deployment_id: str) -> list[Any]:
        for r in rows:
            await store.put_row(r)
        return list(await store.list_rows(deployment_id))


# --------------------------------------------------------------------------- orchestration


def _validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", args.subscription):
        raise RefusedError("--subscription must be a subscription id (guid)")
    if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", args.resource_group):
        raise RefusedError("--resource-group has unsupported characters")
    loc = args.location.strip().lower()
    if is_government_location(loc) or not re.fullmatch(r"[a-z0-9]+", loc):
        raise RefusedError(
            f"location {args.location!r} is not a Commercial region; Government regions "
            "(usgov*/usdod*) are refused. No changes made."
        )
    if args.reuse_apim:
        if not re.fullmatch(
            r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
            r"Microsoft\.ApiManagement/service/[^/]+",
            args.reuse_apim,
            re.I,
        ):
            raise RefusedError("--reuse-apim must be an Microsoft.ApiManagement/service ARM id")
    elif not (args.apim_publisher_email and args.apim_publisher_name):
        raise RefusedError(
            "creating APIM requires --apim-publisher-email and --apim-publisher-name "
            "(or pass --reuse-apim)"
        )


def _markdown(ev: dict[str, Any]) -> str:
    lines = [
        f"# G01 Commercial deploy smoke - {ev['result']}",
        "",
        f"- Gate: {ev['gate']} (Commercial only; Government stays OPEN)",
        f"- Script version: {ev['script_version']}",
        f"- Window (UTC): {ev['started_utc']} to {ev['finished_utc']}",
        f"- Subscription: {ev['subscription_id']}",
        f"- Resource group: {ev['resource_group']} ({ev['location']})",
        f"- Health: {'OK' if ev['health'].get('ok') else 'NOT OK'}",
        f"- Teardown performed: {ev['teardown'].get('performed')} ok: {ev['teardown'].get('ok')}",
        "",
        "## Resources created",
        "",
    ]
    lines += [
        f"- {r['type']} {r['id']} ({r['provisioningState']})" for r in ev["resources_created"]
    ] or ["- none"]
    lines += ["", "## Steps", ""]
    lines += [f"- [{s['status']}] {s['step']} {s['detail']}".rstrip() for s in ev["steps"]]
    if ev.get("errors"):
        lines += ["", "## Errors", ""] + [f"- {e}" for e in ev["errors"]]
    return "\n".join(lines) + "\n"


def _write_evidence(evidence: dict[str, Any], evidence_dir: Path) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    day = _utcnow().strftime("%Y-%m-%d")
    path = evidence_dir / f"{day}-commercial-deploy-smoke.json"
    if path.exists():
        path = evidence_dir / f"{day}-{_utcnow().strftime('%H%M%S')}-commercial-deploy-smoke.json"
    evidence = redact_subscriptions(evidence, [str(evidence.get("subscription_id") or "")])
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(_markdown(evidence), encoding="utf-8")
    return path


def run(args: argparse.Namespace, runner: AzRunner, work_dir: Path) -> int:
    started = _utcnow()
    try:
        _validate(args)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    smoke = Smoke(
        run_az=runner,
        subscription=args.subscription,
        resource_group=args.resource_group,
        location=args.location.strip().lower(),
        reuse_apim=args.reuse_apim,
        publisher_email=args.apim_publisher_email,
        publisher_name=args.apim_publisher_name,
        keep=args.keep,
        work_dir=work_dir,
    )
    try:
        smoke.preflight()
    except (RefusedError, AzError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if not args.reuse_apim:
        print(
            "WARNING: creating API Management (Developer) takes ~30-45 minutes. Teardown will "
            "also purge the soft-deleted Key Vault and APIM service."
        )

    errors: list[str] = []
    what_if: dict[str, Any] = {}
    deployment: dict[str, Any] = {}
    resources: list[dict[str, str]] | None = None
    health: dict[str, Any] = {"ok": False}
    params_path: Path | None = None
    try:
        smoke.create_resource_group()
        params_path = smoke._parameters_file()  # pyright: ignore[reportPrivateUsage]
        arg = f"@{params_path}"
        what_if = smoke.what_if(arg)
        deployment = smoke.deploy(arg)
        resources = smoke.list_resources()
        health = smoke.health(resources, deployment["provisioningState"])
        smoke.step("health", "ok" if health["ok"] else "failed", f"{len(resources)} resources")
        if not health["ok"]:
            errors.append("health check failed")
    except (AzError, RefusedError, ValueError) as exc:
        errors.append(safe_text(str(exc)))
        smoke.step("deploy-flow", "failed", safe_text(str(exc)))
    finally:
        if params_path is not None:
            params_path.unlink(missing_ok=True)

    teardown: dict[str, Any] = {"performed": False, "ok": True, "steps": [], "purge": {}}
    if smoke.rg_created and not args.keep:
        teardown = smoke.teardown(resources)
        if not teardown["ok"]:
            errors.append("teardown did not complete cleanly")
    elif args.keep:
        smoke.step("teardown", "skipped", "--keep set; resource group left in place")
        teardown = {"performed": False, "ok": True, "steps": smoke.steps[-1:], "purge": {}}

    passed = not errors and health["ok"] and teardown["ok"]
    evidence: dict[str, Any] = {
        "gate": GATE,
        "result": "PASS" if passed else "FAIL",
        "script_version": SCRIPT_VERSION,
        "cloud": "commercial",
        "started_utc": _iso(started),
        "finished_utc": _iso(_utcnow()),
        "subscription_id": smoke.subscription,
        "resource_group": smoke.resource_group,
        "resource_group_created_by_script": smoke.rg_created,
        "location": smoke.location,
        "reused_apim": smoke.reuse_apim or None,
        "kept": bool(args.keep),
        "what_if": what_if,
        "deployment": deployment,
        "resources_created": [
            {"type": r["type"], "id": r["id"], "provisioningState": r["provisioningState"]}
            for r in (resources or [])
        ],
        "health": health,
        "teardown": teardown,
        "steps": smoke.steps,
        "errors": errors,
    }
    try:
        scrub(evidence)
    except ScrubError as exc:
        print(f"ERROR: evidence scrubber rejected the run: {exc}", file=sys.stderr)
        evidence = {
            "gate": GATE,
            "result": "FAIL",
            "script_version": SCRIPT_VERSION,
            "cloud": "commercial",
            "started_utc": evidence["started_utc"],
            "finished_utc": evidence["finished_utc"],
            "subscription_id": smoke.subscription,
            "resource_group": smoke.resource_group,
            "location": smoke.location,
            "what_if": {},
            "deployment": {},
            "resources_created": [],
            "health": {"ok": False},
            "teardown": {"performed": teardown["performed"], "ok": False, "steps": [], "purge": {}},
            "steps": [],
            "errors": ["evidence scrubber rejected the collected data (values withheld)"],
        }
        passed = False
    path = _write_evidence(evidence, Path(args.evidence_dir))
    print(f"{evidence['result']}: wrote {path}")
    if not passed and smoke.rg_created and (args.keep or not teardown["performed"]):
        print(
            f"NOTE: resource group {smoke.resource_group} may still exist and incur cost; "
            "review and remove it manually.",
            file=sys.stderr,
        )
    return 0 if passed else 1


def main(
    argv: list[str] | None = None,
    *,
    runner: AzRunner | None = None,
    work_dir: Path | None = None,
) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g01_deploy_smoke.py deploys billable Azure resources and needs operator "
            "approval; set NS_LIVE_APPROVED=1. No az command was run.",
            file=sys.stderr,
        )
        return 2

    args = build_parser().parse_args(argv)
    # Teardown needs the ownership register; prove it imports before anything is created, so a
    # wrong interpreter cannot leave a billable resource group behind (observed 2026-10-16).
    try:
        import neurosphere_core.deploy.register  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError:
        print(
            "REFUSED: neurosphere_core is not importable; run with `uv run python "
            "scripts/gates/g01_deploy_smoke.py ...`. No az command was run.",
            file=sys.stderr,
        )
        return 2
    if runner is None:
        az_path = shutil.which("az")
        if not az_path:
            print("REFUSED: the Azure CLI (az) was not found on PATH.", file=sys.stderr)
            return 2
        runner = SubprocessAzRunner(az_path)
    with (
        tempfile.TemporaryDirectory(prefix="g01-") if work_dir is None else _NullCtx(work_dir) as wd
    ):
        return run(args, runner, Path(wd))


class _NullCtx:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> Path:
        return self._path

    def __exit__(self, *_exc: object) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
