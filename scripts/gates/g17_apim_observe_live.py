"""G17 live run: APIM AI gateway observe (PRP-33 item 8), Azure Commercial only.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before argument
parsing, any import of project code, or any `az` invocation). This creates BILLABLE Azure
resources (one Standard v2 API Management service plus a Log Analytics workspace, under an hour)
in a resource group this script creates, makes ONE paid model call through the gateway, reads the
gateway back through the NeuroSphere observe path (preflight, inventory, connector APIM_GATEWAY
kind), writes evidence and tears down only what it created.

Preconditions (operator): `az` is installed and signed in to the Commercial cloud (`AzureCloud`)
with the target (Limitlessdata) subscription active. The script never logs in. The gateway
subscription key is read in memory once (ARM `listSecrets`), used for one request and never
printed, logged or written (evidence carries `<key:redacted>`).

RBAC on the shared Foundry resource (APIM identity -> Cognitive Services OpenAI User) is a
per-step operator approval point: without --approve-rbac the exact command is printed, the phase
is recorded `skipped_awaiting_operator` and the run goes straight to teardown.

Evidence: docs/evidence/G17/observe-<UTC stamp>.{json,md}.

Exit codes: 0 PASS (or PARTIAL_OPEN when RBAC was left to the operator), 1 FAIL, 2 REFUSED
(approval, cloud, argument precondition; nothing changed), 3 teardown failure (orphan list).
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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = Path(__file__).resolve().parents[2]
SCRIPT_VERSION = "1.0.0"
GATE = "G17"
DEFAULT_LOCATION = "centralus"
CREATED_BY_TAG = "neurosphere:created-by=g17"
GATE_TAG = "neurosphere:gate=G17"
TAG_KEY = "neurosphere:created-by"
TAG_VALUE = "g17"
ARM = "https://management.azure.com"
APIM_API_VERSION = "2024-05-01"
CHAT_API_VERSION = "2024-10-21"
API_ID = "g17-llm"
API_PATH = "llm"
OPENAI_USER_ROLE = "Cognitive Services OpenAI User"
AZ_TIMEOUT_SECONDS = 30 * 60
POLL_SECONDS = 60
FIXED_PROMPT = "Reply with the single word: ok"
KEY_REDACTED = "<key:redacted>"
_GOV_PREFIXES = ("usgov", "usdod")


class AzResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


class AzRunner(Protocol):
    def __call__(self, args: Sequence[str]) -> AzResult: ...


class SubprocessAzRunner:
    """The real runner: resolved `az`, list args, no shell, MSYS path conversion off."""

    def __init__(self, az_path: str) -> None:
        self._az = az_path

    def __call__(self, args: Sequence[str]) -> AzResult:
        env = {**os.environ, "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}
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
            env=env,
        )
        return AzResult(proc.returncode, proc.stdout, proc.stderr)


class GateError(RuntimeError):
    pass


class RefusedError(RuntimeError):
    pass


# --------------------------------------------------------------------------- tokenisation

_SUBSCRIPTION_IN_ID = re.compile(r"/subscriptions/([0-9a-fA-F-]{36})", re.IGNORECASE)
REDACTION_NOTES = (
    "subscription ids replaced with <subscription:sha256-8> (first 8 hex of the SHA-256 of the "
    "lowercase id); the repository is public",
    "gateway subscription key never read into evidence (<key:redacted>)",
)


def subscription_token(subscription_id: str) -> str:
    digest = hashlib.sha256(subscription_id.strip().lower().encode("utf-8")).hexdigest()
    return f"<subscription:{digest[:8]}>"


def host_token(host: str) -> str:
    digest = hashlib.sha256(host.strip().lower().encode("utf-8")).hexdigest()
    return f"<host:{digest[:8]}>"


def _collect(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():  # pyright: ignore[reportUnknownVariableType]
            _collect(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            _collect(item, found)
    elif isinstance(value, str):
        found.update(m.lower() for m in _SUBSCRIPTION_IN_ID.findall(value))


def _replace(value: Any, pairs: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {k: _replace(v, pairs) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_replace(v, pairs) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str):
        out = value
        for needle, token in pairs:
            out = re.sub(re.escape(needle), token, out, flags=re.IGNORECASE)
        return out
    return value


def redact(
    evidence: dict[str, Any],
    *,
    subscriptions: Sequence[str] = (),
    secrets: Sequence[str] = (),
    hosts: Sequence[str] = (),
) -> dict[str, Any]:
    """Tokenise subscription ids and hosts; replace any known secret value with a marker."""
    found = {s.strip().lower() for s in subscriptions if s}
    _collect(evidence, found)
    pairs: list[tuple[str, str]] = [(s, "<key:redacted>") for s in secrets if s]
    pairs += [(s, subscription_token(s)) for s in sorted(found)]
    pairs += [(h, host_token(h)) for h in hosts if h]
    out = _replace(evidence, pairs)
    out["redactions"] = list(REDACTION_NOTES)
    return out


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def is_government_location(location: str) -> bool:
    return location.strip().lower().startswith(_GOV_PREFIXES)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="G17 APIM observe live gate (operator-approved).")
    ap.add_argument("--subscription", required=True, help="Commercial subscription id (guid)")
    ap.add_argument("--location", default=DEFAULT_LOCATION, help="Commercial region")
    ap.add_argument("--foundry-endpoint", required=True, help="https URL of the Foundry/OpenAI")
    ap.add_argument("--foundry-deployment", required=True, help="model deployment name")
    ap.add_argument("--resource-group", default=f"ns-g17-{_stamp(_utcnow()).lower()}")
    ap.add_argument("--budget-minutes", type=int, default=20)
    ap.add_argument("--keep", action="store_true", help="skip teardown (default: tear down)")
    ap.add_argument("--purge", action="store_true", help="also purge the soft-deleted workspace")
    ap.add_argument("--approve-rbac", action="store_true", help="run the OpenAI User RBAC write")
    ap.add_argument("--publisher-email", default="g17-gate@example.com")
    ap.add_argument("--evidence-dir", default=str(REPO / "docs" / "evidence" / "G17"))
    return ap


# --------------------------------------------------------------------------- register


@dataclass
class Owned:
    resource_id: str
    kind: str
    ownership: str  # created | preexisting


@dataclass
class Register:
    items: list[Owned] = field(default_factory=lambda: [])

    def add(self, resource_id: str, kind: str, ownership: str = "created") -> None:
        self.items.append(Owned(resource_id, kind, ownership))

    def created(self, kind: str) -> list[Owned]:
        return [i for i in self.items if i.kind == kind and i.ownership == "created"]


# --------------------------------------------------------------------------- the run

Sender = Callable[[str, dict[str, str], dict[str, Any]], "tuple[int, dict[str, str]]"]
Observer = Callable[["Gate"], "dict[str, Any]"]
RowFetcher = Callable[[str, int], "list[dict[str, Any]]"]
Sleeper = Callable[[float], None]


def _default_sender(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> tuple[int, dict[str, str]]:
    import httpx

    resp = httpx.post(url, headers=headers, json=body, timeout=60.0)
    return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}


@dataclass
class Gate:
    run_az: AzRunner
    subscription: str
    location: str
    resource_group: str
    foundry_endpoint: str
    foundry_deployment: str
    budget_minutes: int = 20
    keep: bool = False
    purge: bool = False
    approve_rbac: bool = False
    publisher_email: str = "g17-gate@example.com"
    sender: Sender = _default_sender
    observer: Observer | None = None
    row_fetcher: RowFetcher | None = None
    sleep: Sleeper = time.sleep
    clock: Callable[[], float] = time.monotonic
    register: Register = field(default_factory=Register)
    phases: list[dict[str, Any]] = field(default_factory=lambda: [])
    facts: dict[str, Any] = field(default_factory=lambda: {})
    rg_created: bool = False
    _key: str = ""

    # ---- helpers
    @property
    def apim_name(self) -> str:
        return "nsg17" + hashlib.sha256(self.resource_group.encode()).hexdigest()[:8]

    @property
    def workspace_name(self) -> str:
        return f"{self.resource_group}-law"

    @property
    def rg_id(self) -> str:
        return f"/subscriptions/{self.subscription}/resourceGroups/{self.resource_group}"

    @property
    def apim_id(self) -> str:
        return f"{self.rg_id}/providers/Microsoft.ApiManagement/service/{self.apim_name}"

    def az(self, args: Sequence[str], *, sensitive: bool = False) -> AzResult:
        print(f"  az {' '.join(args[:4])} ...", flush=True)
        res = self.run_az([*args, "--only-show-errors"] if args[0] != "rest" else list(args))
        if res.rc != 0:
            msg = "" if sensitive else " ".join(res.stderr.split())[:300]
            raise GateError(f"az {' '.join(args[:3])} failed (rc={res.rc}) {msg}".strip())
        return res

    def az_json(self, args: Sequence[str]) -> Any:
        res = self.az([*args, "-o", "json"])
        return json.loads(res.stdout) if res.stdout.strip() else None

    def rest(self, method: str, path: str, body: dict[str, Any] | None, api: str) -> Any:
        sep = "&" if "?" in path else "?"
        args = ["rest", "--method", method, "--url", f"{ARM}{path}{sep}api-version={api}"]
        tmp: str | None = None
        if body is not None:
            fd, tmp = tempfile.mkstemp(suffix=".json", prefix="g17-body-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(body, fh)
            args += ["--body", f"@{tmp}"]
        try:
            res = self.az(args, sensitive=path.endswith("listSecrets"))
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
        return json.loads(res.stdout) if res.stdout.strip() else None

    def phase(self, name: str, fn: Callable[[], dict[str, Any] | None]) -> bool:
        print(f"[phase {name}]", flush=True)
        start = self.clock()
        status, detail = "pass", {}
        try:
            out = fn()
            detail = dict(out or {})
            status = str(detail.pop("status", "pass"))
        except Exception as exc:
            status, detail = "fail", {"error": str(exc)[:400]}
        self.phases.append(
            {
                "phase": name,
                "status": status,
                "duration_s": round(self.clock() - start, 1),
                **detail,
            }
        )
        print(f"[phase {name}] {status}", flush=True)
        return status in ("pass", "skipped_awaiting_operator")

    # ---- phase 1
    def create_infra(self) -> dict[str, Any]:
        self.az(
            [
                "group",
                "create",
                "-n",
                self.resource_group,
                "-l",
                self.location,
                "--subscription",
                self.subscription,
                "--tags",
                CREATED_BY_TAG,
                GATE_TAG,
            ]
        )
        self.rg_created = True
        self.register.add(self.rg_id, "resource_group")
        law = self.az_json(
            [
                "monitor",
                "log-analytics",
                "workspace",
                "create",
                "-g",
                self.resource_group,
                "-n",
                self.workspace_name,
                "-l",
                self.location,
                "--subscription",
                self.subscription,
                "--tags",
                CREATED_BY_TAG,
                GATE_TAG,
            ]
        )
        self.facts["workspace_id"] = str(law["id"])
        self.facts["workspace_customer_id"] = str(law["customerId"])
        self.register.add(self.facts["workspace_id"], "workspace")
        body = {
            "location": self.location,
            "sku": {"name": "StandardV2", "capacity": 1},
            "identity": {"type": "SystemAssigned"},
            "tags": {TAG_KEY: TAG_VALUE, "neurosphere:gate": GATE},
            "properties": {
                "publisherEmail": self.publisher_email,
                "publisherName": "NeuroSphere G17",
            },
        }
        self.register.add(self.apim_id, "apim")
        self.rest("PUT", self.apim_id, body, APIM_API_VERSION)
        deadline = self.clock() + self.budget_minutes * 60
        while True:
            svc = self.rest("GET", self.apim_id, None, APIM_API_VERSION) or {}
            state = str((svc.get("properties") or {}).get("provisioningState", ""))
            if state == "Succeeded":
                ident = svc.get("identity") or {}
                self.facts["apim_principal_id"] = str(ident.get("principalId", ""))
                self.facts["apim_gateway_url"] = str(
                    (svc.get("properties") or {}).get("gatewayUrl", "")
                )
                return {"provisioning_state": state, "sku": "StandardV2"}
            if state in ("Failed", "Canceled"):
                raise GateError(f"APIM provisioningState {state}")
            if self.clock() >= deadline:
                raise GateError("APIM creation exceeded the budget")
            self.sleep(POLL_SECONDS)

    # ---- phase 2
    def diagnostics(self) -> dict[str, Any]:
        logs = json.dumps(
            [
                {"category": "GatewayLogs", "enabled": True},
                {"category": "GatewayLlmLogs", "enabled": True},
            ]
        )
        self.az(
            [
                "monitor",
                "diagnostic-settings",
                "create",
                "--name",
                "g17-diag",
                "--resource",
                self.apim_id,
                "--workspace",
                self.facts["workspace_id"],
                "--logs",
                logs,
                "--export-to-resource-specific",
                "true",
            ]
        )
        return {"categories": ["GatewayLogs", "GatewayLlmLogs"]}

    # ---- phase 3
    def foundry_id(self) -> str:
        host = (urlparse(self.foundry_endpoint).hostname or "").lower()
        accounts = (
            self.az_json(
                ["cognitiveservices", "account", "list", "--subscription", self.subscription]
            )
            or []
        )
        for acct in accounts:
            ep = str((acct.get("properties") or {}).get("endpoint", ""))
            if (urlparse(ep).hostname or "").lower() == host:
                return str(acct["id"])
        raise GateError("no Cognitive Services account in the subscription matches the endpoint")

    def rbac_command(self, scope: str) -> list[str]:
        return [
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            self.facts.get("apim_principal_id", "<apim-principal-id>"),
            "--assignee-principal-type",
            "ServicePrincipal",
            "--role",
            OPENAI_USER_ROLE,
            "--scope",
            scope,
        ]

    def import_api(self) -> dict[str, Any]:
        api_path = f"{self.apim_id}/apis/{API_ID}"
        self.rest(
            "PUT",
            api_path,
            {
                "properties": {
                    "displayName": "G17 LLM",
                    "path": API_PATH,
                    "protocols": ["https"],
                    "serviceUrl": f"{self.foundry_endpoint.rstrip('/')}/openai",
                    "subscriptionRequired": True,
                }
            },
            APIM_API_VERSION,
        )
        self.rest(
            "PUT",
            f"{api_path}/operations/chat-completions",
            {
                "properties": {
                    "displayName": "chat completions",
                    "method": "POST",
                    "urlTemplate": "/deployments/{deployment}/chat/completions",
                    "templateParameters": [
                        {"name": "deployment", "type": "string", "required": True}
                    ],
                }
            },
            APIM_API_VERSION,
        )
        xml = (
            "<policies><inbound><base />"
            '<authentication-managed-identity resource="https://cognitiveservices.azure.com" />'
            '<llm-emit-token-metric namespace="ns-g17"><dimension name="API ID" />'
            "</llm-emit-token-metric></inbound><backend><base /></backend>"
            "<outbound><base /></outbound><on-error><base /></on-error></policies>"
        )
        self.rest(
            "PUT",
            f"{api_path}/policies/policy",
            {"properties": {"format": "rawxml", "value": xml}},
            APIM_API_VERSION,
        )
        return {"api": API_ID, "operation": "POST /deployments/{deployment}/chat/completions"}

    def grant_rbac(self) -> dict[str, Any]:
        scope = self.foundry_id()
        self.facts["foundry_resource_id"] = scope
        cmd = self.rbac_command(scope)
        if not self.approve_rbac:
            print("OPERATOR APPROVAL REQUIRED (RBAC write on a shared resource). Command:")
            print("  az " + " ".join(cmd))
            print("Re-run with --approve-rbac to let the gate run it.")
            self.facts["rbac"] = "skipped_awaiting_operator"
            return {"status": "skipped_awaiting_operator", "command": "az " + " ".join(cmd)}
        existing = (
            self.az_json(
                [
                    "role",
                    "assignment",
                    "list",
                    "--assignee",
                    self.facts["apim_principal_id"],
                    "--scope",
                    scope,
                    "--role",
                    OPENAI_USER_ROLE,
                ]
            )
            or []
        )
        if existing:
            self.facts["rbac"] = "applied"
            self.register.add(str(existing[0]["id"]), "role_assignment", "preexisting")
            return {"note": "assignment already existed; left in place"}
        created = self.az_json(cmd)
        self.register.add(str(created["id"]), "role_assignment")
        self.facts["rbac"] = "applied"
        return {"role": OPENAI_USER_ROLE}

    def create_key(self) -> None:
        sub_path = f"{self.apim_id}/subscriptions/g17-sub"
        self.rest(
            "PUT",
            sub_path,
            {
                "properties": {
                    "scope": f"{self.apim_id}/apis/{API_ID}",
                    "displayName": "g17-sub",
                    "state": "active",
                }
            },
            APIM_API_VERSION,
        )
        secrets = self.rest("POST", f"{sub_path}/listSecrets", None, APIM_API_VERSION) or {}
        self._key = str(secrets.get("primaryKey", ""))
        if not self._key:
            raise GateError("subscription key could not be read")

    # ---- phase 4
    def send_request(self) -> dict[str, Any]:
        self.create_key()
        base = self.facts.get("apim_gateway_url") or f"https://{self.apim_name}.azure-api.net"
        url = (
            f"{base.rstrip('/')}/{API_PATH}/deployments/{self.foundry_deployment}"
            f"/chat/completions?api-version={CHAT_API_VERSION}"
        )
        body = {"messages": [{"role": "user", "content": FIXED_PROMPT}], "max_tokens": 8}
        status, headers = self.sender(url, {"Ocp-Apim-Subscription-Key": self._key}, body)
        corr = headers.get("x-ms-request-id") or headers.get("request-id") or ""
        self.facts["request_status"] = status
        self.facts["correlation_id"] = corr
        if status != 200:
            raise GateError(f"gateway request returned HTTP {status}")
        return {
            "status_code": status,
            "correlation_id": corr,
            "paid_model_calls": 1,
            "note": "one paid chat completion, max_tokens 8",
        }

    # ---- phase 5
    def observe(self) -> dict[str, Any]:
        corr = str(self.facts.get("correlation_id", ""))
        deadline = self.clock() + self.budget_minutes * 60
        snapshot: dict[str, Any] = {}
        attempts = 0
        while True:
            attempts += 1
            if self.observer is not None and not snapshot:
                snapshot = self.observer(self)
            rows = (
                self.row_fetcher(self.facts["workspace_customer_id"], 30)
                if self.row_fetcher
                else []
            )
            match = [r for r in rows if corr and str(r.get("CorrelationId", "")) == corr]
            mode = "correlation_id"
            if not match:
                match = [r for r in rows if str(r.get("ApiId", "")) == API_ID]
                mode = "api_id_fallback"
            if match:
                row = match[0]
                tokens = row.get("TotalTokens")
                llm = "observed" if tokens not in (None, "", 0) else "not_observed"
                self.facts["llm_log_row"] = llm
                return {
                    **snapshot,
                    "attempts": attempts,
                    "gateway_row": "observed",
                    "match_mode": mode,
                    "llm_log_row": llm,
                    "connector_row": row,
                }
            if self.clock() >= deadline:
                self.facts["llm_log_row"] = "not_observed"
                raise GateError("no gateway row appeared within the budget")
            self.sleep(POLL_SECONDS)

    # ---- phase 6
    def teardown(self) -> dict[str, Any]:
        orphans: list[str] = []
        for ra in self.register.created("role_assignment"):
            try:
                self.az(["role", "assignment", "delete", "--ids", ra.resource_id])
            except GateError:
                orphans.append(ra.resource_id)
        if self.rg_created:
            listing = (
                self.az_json(
                    [
                        "resource",
                        "list",
                        "-g",
                        self.resource_group,
                        "--subscription",
                        self.subscription,
                    ]
                )
                or []
            )
            untagged = [
                str(r.get("id")) for r in listing if (r.get("tags") or {}).get(TAG_KEY) != TAG_VALUE
            ]
            if untagged:
                orphans.append(self.rg_id)
                raise TeardownRefusedError(untagged, orphans)
            try:
                self.az(
                    [
                        "group",
                        "delete",
                        "-n",
                        self.resource_group,
                        "--yes",
                        "--subscription",
                        self.subscription,
                    ]
                )
            except GateError:
                orphans.append(self.rg_id)
        if self.purge and not orphans:
            try:
                self.az(
                    [
                        "monitor",
                        "log-analytics",
                        "workspace",
                        "delete",
                        "-g",
                        self.resource_group,
                        "-n",
                        self.workspace_name,
                        "--force",
                        "true",
                        "--yes",
                    ]
                )
            except GateError:
                orphans.append(self.facts.get("workspace_id", self.workspace_name))
        if orphans:
            raise TeardownRefusedError([], orphans)
        return {"deleted": [i.resource_id for i in self.register.items if i.ownership == "created"]}


class TeardownRefusedError(RuntimeError):
    def __init__(self, untagged: list[str], orphans: list[str]) -> None:
        super().__init__(f"teardown incomplete; untagged={untagged} orphans={orphans}")
        self.untagged = untagged
        self.orphans = orphans


def run_gate(gate: Gate) -> tuple[int, dict[str, Any]]:
    """Run phases 1-6; returns (exit code, evidence dict before redaction)."""
    ok = gate.phase("1-create", gate.create_infra)
    ok = ok and gate.phase("2-diagnostics", gate.diagnostics)
    ok = ok and gate.phase("3-import-api", gate.import_api)
    rbac_ok = ok and gate.phase("3-rbac", gate.grant_rbac)
    gate.facts.setdefault("rbac", "skipped_awaiting_operator")
    partial = False
    if ok and rbac_ok and gate.facts["rbac"] == "applied":
        ok = gate.phase("4-request", gate.send_request)
        ok = ok and gate.phase("5-observe", gate.observe)
    elif ok and rbac_ok:
        partial = True
        gate.facts["llm_log_row"] = "skipped"
        for name in ("4-request", "5-observe"):
            gate.phases.append(
                {"phase": name, "status": "skipped_awaiting_operator", "duration_s": 0.0}
            )
    else:
        ok = False
    gate.facts.setdefault("llm_log_row", "skipped")
    teardown_code = 0
    orphans: list[str] = []
    if gate.keep:
        gate.phases.append({"phase": "6-teardown", "status": "skipped_keep", "duration_s": 0.0})
    else:
        start = gate.clock()
        try:
            detail = gate.teardown()
            gate.phases.append(
                {
                    "phase": "6-teardown",
                    "status": "pass",
                    "duration_s": round(gate.clock() - start, 1),
                    **detail,
                }
            )
        except TeardownRefusedError as exc:
            teardown_code, orphans = 3, exc.orphans
            gate.phases.append(
                {
                    "phase": "6-teardown",
                    "status": "fail",
                    "duration_s": round(gate.clock() - start, 1),
                    "untagged_resources": exc.untagged,
                    "orphans": exc.orphans,
                }
            )
        except GateError as exc:
            teardown_code, orphans = 3, [gate.rg_id]
            gate.phases.append(
                {
                    "phase": "6-teardown",
                    "status": "fail",
                    "error": str(exc)[:300],
                    "orphans": orphans,
                    "duration_s": round(gate.clock() - start, 1),
                }
            )
    result = "PASS" if ok and not partial else ("PARTIAL_OPEN" if ok and partial else "FAIL")
    evidence = build_evidence(gate, result, orphans)
    code = 3 if teardown_code else (0 if result in ("PASS", "PARTIAL_OPEN") else 1)
    return code, evidence


def build_evidence(gate: Gate, result: str, orphans: list[str]) -> dict[str, Any]:
    observe = next((p for p in gate.phases if p["phase"] == "5-observe"), {})
    return {
        "gate": GATE,
        "script_version": SCRIPT_VERSION,
        "run_at": _utcnow().isoformat(),
        "result": result,
        "cloud": "commercial",
        "subscription": gate.subscription,
        "location": gate.location,
        "resource_group": gate.resource_group,
        "apim_resource_id": gate.apim_id,
        "workspace_resource_id": gate.facts.get("workspace_id"),
        "foundry_resource_id": gate.facts.get("foundry_resource_id"),
        "tier": observe.get("tier", "standard_v2" if gate.facts.get("apim_principal_id") else None),
        "paid_model_calls": 1 if gate.facts.get("request_status") == 200 else 0,
        "rbac": gate.facts.get("rbac", "skipped_awaiting_operator"),
        "llm_log_row": gate.facts.get("llm_log_row", "skipped"),
        "phases": gate.phases,
        "register": [
            {"id": i.resource_id, "kind": i.kind, "ownership": i.ownership}
            for i in gate.register.items
        ],
        "orphans": orphans,
        "gateway_key": KEY_REDACTED,
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        f"# G17 APIM observe live run: {evidence['result']}",
        "",
        f"- Run at: {evidence['run_at']}",
        f"- Cloud: {evidence['cloud']}; location: {evidence['location']}",
        f"- RBAC: {evidence['rbac']}; LLM log row: {evidence['llm_log_row']}",
        f"- Paid model calls: {evidence['paid_model_calls']}",
        f"- Gateway key: {evidence['gateway_key']}",
        "",
        "| Phase | Status | Duration (s) |",
        "|---|---|---|",
    ]
    for p in evidence["phases"]:
        lines.append(f"| {p['phase']} | {p['status']} | {p.get('duration_s', 0)} |")
    if evidence.get("orphans"):
        lines += ["", "Orphans (remove manually): " + ", ".join(evidence["orphans"])]
    lines += ["", "Redactions: " + "; ".join(evidence.get("redactions", []))]
    return "\n".join(lines) + "\n"


def write_evidence(
    evidence: dict[str, Any],
    out_dir: Path,
    *,
    secrets: Sequence[str] = (),
    hosts: Sequence[str] = (),
) -> Path:
    clean = redact(
        evidence, subscriptions=[evidence.get("subscription", "")], secrets=secrets, hosts=hosts
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"observe-{_stamp(_utcnow())}"
    base.with_suffix(".json").write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(render_markdown(clean), encoding="utf-8")
    return base.with_suffix(".md")


# --------------------------------------------------------------------------- real observers


def _real_observer(gate: Gate) -> dict[str, Any]:  # pragma: no cover - live only
    from neurosphere_core.clients import arm_client
    from neurosphere_core.cloud.profile import CloudName, profile_for
    from neurosphere_core.gateway import gateway_id_for, preflight, read_inventory

    async def go() -> dict[str, Any]:
        async with arm_client(profile_for(CloudName.COMMERCIAL)) as client:
            pre = await preflight(client, gate.apim_id)
            inv = await read_inventory(
                client,
                gate.apim_id,
                gateway_id=gateway_id_for("g17", "g17", gate.apim_id),
            )
            return {
                "tier": pre.tier,
                "diagnostics": pre.diagnostics.model_dump(),
                "inventory_counts": inv.counts(),
            }

    return asyncio.run(go())


def _real_row_fetcher(
    gate: Gate,
) -> RowFetcher:  # pragma: no cover - live only
    from neurosphere_connector_azure_monitor.gateway_mapping import map_gateway_row
    from neurosphere_connector_azure_monitor.queries import SourceKind, template_for

    def fetch(workspace_customer_id: str, minutes: int) -> list[dict[str, Any]]:
        res = gate.az(
            [
                "monitor",
                "log-analytics",
                "query",
                "-w",
                workspace_customer_id,
                "--analytics-query",
                template_for(SourceKind.APIM_GATEWAY),
                "--timespan",
                f"PT{minutes}M",
                "-o",
                "json",
            ]
        )
        rows: list[dict[str, Any]] = json.loads(res.stdout or "[]")
        for row in rows:
            if row.get("CorrelationId"):
                mapped = map_gateway_row(
                    row, cloud="commercial", customer_id="g17", source_id=workspace_customer_id
                )
                row["_subscription_id_hash"] = mapped.cost.subscription_id_hash
        return rows

    return fetch


# --------------------------------------------------------------------------- main


def main(
    argv: list[str] | None = None, *, runner: AzRunner | None = None, sender: Sender | None = None
) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g17_apim_observe_live.py creates billable Azure resources and makes a paid "
            "model call; set NS_LIVE_APPROVED=1. No az command was run.",
            file=sys.stderr,
        )
        return 2
    args = build_parser().parse_args(argv)
    if is_government_location(args.location):
        print(
            "REFUSED: G17 is Commercial only. Government has no subscription and APIM v2 tiers "
            "are unverified there (OPEN). No az command was run.",
            file=sys.stderr,
        )
        return 2
    if urlparse(args.foundry_endpoint).scheme != "https":
        print("REFUSED: --foundry-endpoint must be an https URL.", file=sys.stderr)
        return 2
    if runner is None:
        az_path = shutil.which("az")
        if not az_path:
            print("REFUSED: the Azure CLI (az) was not found on PATH.", file=sys.stderr)
            return 2
        runner = SubprocessAzRunner(az_path)
    cloud = runner(["cloud", "show", "--query", "name", "-o", "tsv"])
    if cloud.rc != 0 or cloud.stdout.strip() != "AzureCloud":
        print("REFUSED: az is not signed in to the AzureCloud (Commercial) cloud.", file=sys.stderr)
        return 2
    gate = Gate(
        run_az=runner,
        subscription=args.subscription,
        location=args.location,
        resource_group=args.resource_group,
        foundry_endpoint=args.foundry_endpoint,
        foundry_deployment=args.foundry_deployment,
        budget_minutes=args.budget_minutes,
        keep=args.keep,
        purge=args.purge,
        approve_rbac=args.approve_rbac,
        publisher_email=args.publisher_email,
    )
    if sender is not None:
        gate.sender = sender
    else:  # pragma: no cover - live only
        gate.observer = _real_observer
        gate.row_fetcher = _real_row_fetcher(gate)
    code, evidence = run_gate(gate)
    path = write_evidence(
        evidence,
        Path(args.evidence_dir),
        secrets=[gate._key],  # pyright: ignore[reportPrivateUsage]
        hosts=[urlparse(args.foundry_endpoint).hostname or ""],
    )
    print(f"{evidence['result']}: wrote {path}")
    if code == 3:
        print(f"ORPHANS (remove manually): {evidence['orphans']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
