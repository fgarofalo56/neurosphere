"""G17 live run: APIM AI gateway MANAGE mode (PRP-34 item 9), Azure Commercial only.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before argument parsing
and before any `az` or network call). This creates BILLABLE Azure resources (one throwaway
Standard v2 API Management service plus a Log Analytics workspace, under two hours) in a resource
group this script creates, then drives the PRODUCT path against a running NeuroSphere API: every
gateway change is a drafted action intent that is validated, confirmed (and approved when policy
requires) and executed by the worker, never a direct connector call. The reused Loom APIM is
NEVER a manage-mode target: only the throwaway instance created here is ever registered.

Steps (each needs explicit operator approval; see below), in order:
  provision, diagnostics, import-api (Foundry API plus a two-member backend pool), rbac,
  register, snapshot (pre-run inventory), mode-manage (preflight), grant-publish, backend-swap
  (pool canary), cap-change, mcp-publish, mcp-call (Entra token, credentials stripped),
  unpublish (grant, MCP deny then remove, swap and cap restored), inventory-diff, teardown.

Approval: a step runs only when named in --approve-step (repeatable) or --approve-all-steps is
given. An unapproved step prints the exact action, is recorded `skipped_awaiting_operator`, and
every later step is skipped too; teardown still runs (unless --keep). The run is resumable: pass
--state-file and a re-run skips the steps already recorded `pass` there (all az/ARM writes are
idempotent PUTs) and reuses the recorded resource group.

Inputs the operator supplies: a running NeuroSphere API (--api-url) and a bearer token in the
environment variable named by --api-token-env (read in memory, never printed or written; a second
principal in --approver-token-env is used for maker-checker decisions when required), the
catalog ids of an existing Grant and McpServer entity, a throwaway streamable-HTTP MCP backend
that echoes request headers (--mcp-backend-url; `--print-echo-server` prints a stdlib one), and an
approved Foundry endpoint. `az` must be signed in to AzureCloud with the target subscription
(Limitlessdata) active; the script never logs in.

Evidence: docs/evidence/G17/manage-<UTC stamp>.{json,md}. Written only after a run that reached
at least one live step. No evidence file means the gate did not run: G17 manage stays OPEN.

Exit codes: 0 PASS, 1 FAIL, 2 REFUSED (nothing changed) or OPEN (a step awaited the operator),
3 teardown failure (orphan list).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import g17_apim_observe_live as obs  # noqa: E402  (stdlib-only at import; sibling gate helpers)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = obs.REPO
SCRIPT_VERSION = "1.0.0"
GATE = "G17"
RESULT_OPEN = "OPEN"
TOKEN_REDACTED = "<token:redacted>"  # noqa: S105 - a marker, not a credential
API_PREFIX = "/api/v1"
POOL_ID = "g17-pool"
MEMBER_IDS = ("g17-backend-a", "g17-backend-b")
CANARY_WEIGHT = 10
STRIPPED_HEADERS = ("authorization", "ocp-apim-subscription-key")
TERMINAL_OK = "succeeded"
TERMINAL_BAD = ("failed", "rolled_back", "expired")

STEPS: tuple[str, ...] = (
    "provision",
    "diagnostics",
    "import-api",
    "rbac",
    "register",
    "snapshot",
    "mode-manage",
    "grant-publish",
    "backend-swap",
    "cap-change",
    "mcp-publish",
    "mcp-call",
    "unpublish",
    "inventory-diff",
)

REFUSAL = (
    "REFUSED: g17_apim_manage_live.py creates billable Azure resources and performs gateway "
    "writes through the NeuroSphere action executor; set NS_LIVE_APPROVED=1. No az command, "
    "network call or API request was made."
)

ECHO_SERVER_SOURCE = '''\
"""Throwaway streamable-HTTP MCP stand-in: answers every POST with the request headers."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"headers": dict(self.headers.items())}}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''


# --------------------------------------------------------------------------- seams


class ApiClient(Protocol):
    """Authenticated JSON calls to the NeuroSphere API. ``actor`` is ``maker`` or ``approver``."""

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None, *, actor: str = "maker"
    ) -> dict[str, Any]: ...


class ArmReader(Protocol):
    """Read one ARM resource: returns (document, ETag)."""

    def get(self, path: str, api: str) -> tuple[dict[str, Any], str]: ...


class McpCaller(Protocol):
    def __call__(self, url: str, headers: Mapping[str, str], body: dict[str, Any]) -> Any: ...


class HttpApiClient:  # pragma: no cover - live only
    def __init__(self, base: str, maker_token: str, approver_token: str = "") -> None:
        self._base = base.rstrip("/")
        self._tokens = {"maker": maker_token, "approver": approver_token or maker_token}

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None, *, actor: str = "maker"
    ) -> dict[str, Any]:
        import httpx

        resp = httpx.request(
            method,
            f"{self._base}{path}",
            json=body,
            headers={"Authorization": f"Bearer {self._tokens[actor]}"},
            timeout=120.0,
        )
        if resp.status_code >= 400:
            # The body can carry reasons, never credentials; truncate defensively.
            raise obs.GateError(f"API {method} {path} -> HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else {}


class AzArmReader:  # pragma: no cover - live only
    """ETag-aware ARM GET using a short-lived token from `az` held in memory only."""

    def __init__(self, gate: obs.Gate) -> None:
        self._gate = gate

    def get(self, path: str, api: str) -> tuple[dict[str, Any], str]:
        import httpx

        token = self._gate.az(
            [
                "account",
                "get-access-token",
                "--resource",
                obs.ARM,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            sensitive=True,
        ).stdout.strip()
        resp = httpx.get(
            f"{obs.ARM}{path}?api-version={api}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json(), resp.headers.get("etag", "")


def _default_mcp_caller(
    url: str, headers: Mapping[str, str], body: dict[str, Any]
) -> Any:  # pragma: no cover - live only
    import httpx

    resp = httpx.post(url, headers=dict(headers), json=body, timeout=60.0)
    return resp.status_code, resp.json() if resp.content else {}


# --------------------------------------------------------------------------- pure logic


def inventory_signature(inventory: Mapping[str, Any]) -> dict[str, list[str]]:
    """Identity-only signature of a gateway inventory (volatile fields ignored)."""
    sig: dict[str, list[str]] = {}
    for kind in (
        "apis",
        "operations",
        "products",
        "product_api_links",
        "backends",
        "policy_fragments",
        "subscriptions",
    ):
        names: list[str] = []
        for entry in inventory.get(kind) or []:
            if isinstance(entry, Mapping):
                m: Mapping[str, Any] = entry  # pyright: ignore[reportUnknownVariableType]
                ident = m.get("id") or m.get("name") or json.dumps(m, sort_keys=True)
                names.append(str(ident))
            else:
                names.append(str(entry))  # pyright: ignore[reportUnknownArgumentType]
        sig[kind] = sorted(names)
    return sig


def diff_signatures(
    before: Mapping[str, list[str]], after: Mapping[str, list[str]]
) -> dict[str, dict[str, list[str]]]:
    """Per kind: ids ``added`` and ``removed`` since the snapshot. Empty dict means equal."""
    out: dict[str, dict[str, list[str]]] = {}
    for kind in sorted(set(before) | set(after)):
        b, a = set(before.get(kind, [])), set(after.get(kind, []))
        if a != b:
            out[kind] = {"added": sorted(a - b), "removed": sorted(b - a)}
    return out


def find_headers(doc: Any) -> dict[str, str] | None:
    """The first ``headers`` mapping in a JSON document, keys lower-cased."""
    if isinstance(doc, Mapping):
        d: Mapping[str, Any] = doc  # pyright: ignore[reportUnknownVariableType]
        hdrs = d.get("headers")
        if isinstance(hdrs, Mapping):
            h: Mapping[str, Any] = hdrs  # pyright: ignore[reportUnknownVariableType]
            return {str(k).lower(): str(v) for k, v in h.items()}
        for v in d.values():
            found = find_headers(v)
            if found is not None:
                return found
    elif isinstance(doc, list):
        for v in doc:  # pyright: ignore[reportUnknownVariableType]
            found = find_headers(v)
            if found is not None:
                return found
    return None


def leaked_headers(echo: Mapping[str, str]) -> list[str]:
    """Credential headers that reached the backend (the gateway must have stripped them)."""
    return [h for h in STRIPPED_HEADERS if h in echo]


def idempotency_key(step: str, run_id: str) -> str:
    """Stable per (run, step) so a resumed run re-drafts the same intent idempotently."""
    key = re.sub(r"[^A-Za-z0-9._:-]", "-", f"g17m-{run_id}-{step}")
    return key[:128].ljust(16, "0")


def approved(step: str, steps: set[str], all_steps: bool) -> bool:
    return all_steps or step in steps


def _default_fragment_id(grant_entity_id: str) -> str:  # pragma: no cover - live only
    from neurosphere_connector_apim_gateway.cap import grant_fragment_id

    return grant_fragment_id(grant_entity_id)


def _intent(view: Mapping[str, Any]) -> Mapping[str, Any]:
    return view.get("intent") or view  # the ActionView envelope, or a bare intent


# --------------------------------------------------------------------------- the gate


@dataclass
class ManageGate(obs.Gate):
    api: ApiClient | None = None
    arm_reader: ArmReader | None = None
    mcp_caller: McpCaller | None = None
    domain: str = ""
    grant_entity_id: str = ""
    mcp_entity_id: str = ""
    mcp_backend_url: str = ""
    mcp_api_path: str = "g17-mcp"
    mcp_audience: str = ""
    approve_steps: set[str] = field(default_factory=lambda: set())
    approve_all: bool = False
    state_file: Path | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    api_poll_seconds: float = 5.0
    api_budget_seconds: float = 600.0
    events: list[str] = field(default_factory=lambda: [])
    completed: set[str] = field(default_factory=lambda: set())
    blocked: bool = False
    intents: list[dict[str, Any]] = field(default_factory=lambda: [])
    snapshot: dict[str, list[str]] = field(default_factory=lambda: {})
    inventory_diff: dict[str, dict[str, list[str]]] | None = None
    credential_check: dict[str, Any] = field(default_factory=lambda: {})
    cap_original_tpm: int = 1000
    fragment_id_for: Callable[[str], str] | None = None
    _token: str = ""

    # ---- bookkeeping
    @property
    def gateway_id(self) -> str:
        return str(self.facts.get("gateway_id", ""))

    def _api(self) -> ApiClient:
        if self.api is None:
            raise obs.GateError("no NeuroSphere API client configured")
        return self.api

    def _reader(self) -> ArmReader:
        if self.arm_reader is None:
            raise obs.GateError("no ARM reader configured")
        return self.arm_reader

    def _load_state(self) -> None:
        if self.state_file and self.state_file.exists():
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.completed = set(data.get("completed", []))
            self.facts.update(data.get("facts", {}))
            self.run_id = str(data.get("run_id", self.run_id))
            self.snapshot = dict(data.get("snapshot", {}))
            for r in data.get("register", []):
                self.register.add(r["id"], r["kind"], r["ownership"])
            self.rg_created = bool(data.get("rg_created", False))

    def _save_state(self) -> None:
        if not self.state_file:
            return
        facts = {k: v for k, v in self.facts.items() if isinstance(v, (str, int, float, bool))}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "completed": sorted(self.completed),
                    "facts": facts,
                    "snapshot": self.snapshot,
                    "rg_created": self.rg_created,
                    "register": [
                        {"id": i.resource_id, "kind": i.kind, "ownership": i.ownership}
                        for i in self.register.items
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def step(self, name: str, describe: str, fn: Callable[[], dict[str, Any] | None]) -> bool:
        """Run one live step under operator approval; False stops the chain."""
        if self.blocked:
            self.phases.append({"phase": name, "status": "skipped_blocked", "duration_s": 0.0})
            return False
        if name in self.completed:
            self.events.append(f"resume-skip:{name}")
            self.phases.append({"phase": name, "status": "pass", "resumed": True, "duration_s": 0})
            return True
        if not approved(name, self.approve_steps, self.approve_all):
            print(f"OPERATOR APPROVAL REQUIRED for step '{name}': {describe}")
            print(f"Re-run with --approve-step {name} (or --approve-all-steps).")
            self.events.append(f"awaiting:{name}")
            self.phases.append(
                {
                    "phase": name,
                    "status": "skipped_awaiting_operator",
                    "action": describe,
                    "duration_s": 0.0,
                }
            )
            self.blocked = True
            return False
        self.events.append(f"run:{name}")
        ok = self.phase(name, fn)
        if ok:
            self.completed.add(name)
            self._save_state()
        else:
            self.blocked = True
        return ok

    # ---- intents through the real executor path
    def drive(self, step: str, view: Mapping[str, Any]) -> dict[str, Any]:
        """validate -> confirmation -> confirm (-> approver decision) -> wait for the worker."""
        api = self._api()
        intent = _intent(view)
        intent_id = str(intent["intent_id"])
        base = f"{API_PREFIX}/actions/domains/{self.domain}/intents/{intent_id}"
        state = str(intent.get("state"))
        if state in ("drafted",):
            intent = _intent(api.call("POST", f"{base}/validate"))
            state = str(intent.get("state"))
        if state in ("validated",):
            intent = _intent(api.call("POST", f"{base}/confirmation"))
            state = str(intent.get("state"))
        if state == "awaiting_confirmation":
            intent = _intent(
                api.call(
                    "POST", f"{base}/confirm", {"confirmation_hash": intent["confirmation_hash"]}
                )
            )
            state = str(intent.get("state"))
        if state == "awaiting_approval":
            intent = _intent(
                api.call(
                    "POST",
                    f"{base}/decisions",
                    {
                        "decision": "approved",
                        "reason": "G17 manage live gate: operator-approved step",
                        "confirmation_hash": intent["confirmation_hash"],
                    },
                    actor="approver",
                )
            )
        deadline = self.clock() + self.api_budget_seconds
        while True:
            got = api.call("GET", base)
            cur = _intent(got)
            state = str(cur.get("state"))
            if state == TERMINAL_OK:
                execution = got.get("execution") or {}
                rec = {
                    "step": step,
                    "intent_id": intent_id,
                    "action_kind": str(cur.get("action_kind", "")),
                    "state": state,
                    "canary": execution.get("canary"),
                    "verify_matched": execution.get("verify_matched"),
                }
                self.intents.append(rec)
                if execution.get("verify_matched") is False:
                    raise obs.GateError(f"{step}: verify did not match the gateway read-back")
                return rec
            if state in TERMINAL_BAD:
                raise obs.GateError(f"{step}: intent {intent_id} ended {state}")
            if self.clock() >= deadline:
                raise obs.GateError(f"{step}: intent {intent_id} did not finish in the budget")
            self.sleep(self.api_poll_seconds)

    def _ik(self, step: str) -> str:
        return idempotency_key(step, self.run_id)

    def _gw_path(self, suffix: str = "") -> str:
        return f"{API_PREFIX}/gateways/domains/{self.domain}/gateways/{self.gateway_id}{suffix}"

    def _draft_intent(
        self,
        step: str,
        kind: str,
        target: str,
        target_version: str,
        ops: list[dict[str, Any]],
    ) -> dict[str, Any]:
        view = self._api().call(
            "POST",
            f"{API_PREFIX}/actions/domains/{self.domain}/intents",
            {
                "action_kind": kind,
                "target": {"canonical_id": target},
                "target_version": target_version,
                "proposed_diff": {"format": "json_patch", "operations": ops},
                "evidence": [],
                "idempotency_key": self._ik(step),
                "channel": "rest",
            },
        )
        return self.drive(step, view)

    # ---- steps
    def s_register(self) -> dict[str, Any]:
        reg = self._api().call(
            "POST",
            f"{API_PREFIX}/gateways/domains/{self.domain}/gateways",
            {
                "arm_resource_id": self.apim_id,
                "workspace_id": self.facts.get("workspace_id"),
            },
        )
        self.facts["gateway_id"] = str(reg["id"])
        self.facts["customer_id"] = str(reg.get("customer_id", "g17"))
        if reg.get("mode", "observe") != "observe":
            raise obs.GateError("a fresh registration must start in observe mode")
        self._api().call("POST", self._gw_path("/sync"))
        return {"gateway_id": self.gateway_id, "mode": "observe"}

    def s_snapshot(self) -> dict[str, Any]:
        inv = self._api().call("GET", self._gw_path("/inventory"))
        self.snapshot = inventory_signature(inv)
        return {"counts": {k: len(v) for k, v in self.snapshot.items()}}

    def s_mode(self) -> dict[str, Any]:
        view = self._api().call(
            "POST", self._gw_path("/mode"), {"mode": "manage", "idempotency_key": self._ik("mode")}
        )
        rec = self.drive("mode-manage", view)
        det = self._api().call("GET", self._gw_path())
        if det.get("mode") != "manage":
            raise obs.GateError("gateway did not switch to manage")
        return {"intent": rec["intent_id"], "preflight": det.get("preflight")}

    def s_grant_publish(self) -> dict[str, Any]:
        view = self._api().call(
            "POST",
            f"{API_PREFIX}/catalog/grants/{self.grant_entity_id}/publish",
            {
                "gateway_id": self.gateway_id,
                "api_id": obs.API_ID,
                "access": "subscription",
                "idempotency_key": self._ik("grant-publish"),
            },
        )
        rec = self.drive("grant-publish", view)
        return {"intent": rec["intent_id"]}

    def _pool_target(self) -> str:
        cust = self.facts.get("customer_id", "g17")
        return f"commercial:{cust}:apim:apim_backend:{self.gateway_id}/{POOL_ID}"

    def _swap_weight(self, step: str, member_index: int, weight: int) -> dict[str, Any]:
        path = f"{self.apim_id}/backends/{POOL_ID}"
        doc, etag = self._reader().get(path, obs.APIM_API_VERSION)
        base = doc.get("properties", {})
        ops = [
            {"op": "test", "path": "/backend", "value": base},
            {"op": "replace", "path": f"/pool/services/{member_index}/weight", "value": weight},
        ]
        return self._draft_intent(step, "model_deployment_swap", self._pool_target(), etag, ops)

    def s_swap(self) -> dict[str, Any]:
        rec = self._swap_weight("backend-swap", 1, CANARY_WEIGHT)
        canary = rec.get("canary") or {}
        if canary.get("verify_only"):
            raise obs.GateError("pool swap canary was verify-only; expected a real weight shift")
        return {"intent": rec["intent_id"], "canary": canary, "canary_weight": CANARY_WEIGHT}

    def _cap(self, step: str, tpm: int) -> dict[str, Any]:
        frag = (self.fragment_id_for or _default_fragment_id)(self.grant_entity_id)
        _, etag = self._reader().get(f"{self.apim_id}/policyFragments/{frag}", obs.APIM_API_VERSION)
        ops = [
            {"op": "test", "path": "/target/kind", "value": "model"},
            {"op": "test", "path": "/counter_key", "value": "subscription"},
            {"op": "replace", "path": "/limits/tokens_per_minute", "value": tpm},
        ]
        return self._draft_intent(step, "budget_cap_change", self.grant_entity_id, etag, ops)

    def s_cap(self) -> dict[str, Any]:
        rec = self._cap("cap-change", 500)
        return {"intent": rec["intent_id"], "tokens_per_minute": 500}

    def s_mcp_publish(self) -> dict[str, Any]:
        view = self._api().call(
            "POST",
            f"{API_PREFIX}/catalog/mcp-servers/{self.mcp_entity_id}/publish",
            {
                "gateway_id": self.gateway_id,
                "api_path": self.mcp_api_path,
                "idempotency_key": self._ik("mcp-publish"),
            },
        )
        rec = self.drive("mcp-publish", _intent(view.get("action") or view))
        return {"intent": rec["intent_id"], "stage": view.get("stage")}

    def s_mcp_call(self) -> dict[str, Any]:
        token = self.az(
            [
                "account",
                "get-access-token",
                "--resource",
                self.mcp_audience,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            sensitive=True,
        ).stdout.strip()
        self._token = token
        base = self.facts.get("apim_gateway_url") or f"https://{self.apim_name}.azure-api.net"
        url = f"{base.rstrip('/')}/{self.mcp_api_path}/mcp"
        caller = self.mcp_caller or _default_mcp_caller
        status, doc = caller(
            url,
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        echo = find_headers(doc)
        self.credential_check = {
            "http_status": status,
            "echo_headers_seen": echo is not None,
            "leaked": leaked_headers(echo) if echo is not None else [],
        }
        if status != 200 or echo is None:
            raise obs.GateError(f"MCP call through the gateway failed (HTTP {status})")
        if self.credential_check["leaked"]:
            raise obs.GateError("credentials reached the MCP backend: not stripped")
        return {"http_status": status, "credentials_stripped": True}

    def s_unpublish(self) -> dict[str, Any]:
        api = self._api()
        done: list[str] = []
        # MCP: deny first, then remove (two intents, PRP-34 item 6).
        for n in (1, 2):
            view = api.call(
                "POST",
                f"{API_PREFIX}/catalog/mcp-servers/{self.mcp_entity_id}/unpublish",
                {"idempotency_key": self._ik(f"mcp-unpublish-{n}")},
            )
            self.drive(f"mcp-unpublish-{n}", _intent(view.get("action") or view))
            done.append(f"mcp:{view.get('stage')}")
        view = api.call(
            "POST",
            f"{API_PREFIX}/catalog/grants/{self.grant_entity_id}/unpublish",
            {"idempotency_key": self._ik("grant-unpublish")},
        )
        self.drive("grant-unpublish", view)
        done.append("grant")
        self._swap_weight("backend-restore", 1, 0)
        done.append("backend-restore")
        self._cap("cap-restore", self.cap_original_tpm)
        done.append("cap-restore")
        return {"unpublished": done}

    def s_inventory_diff(self) -> dict[str, Any]:
        self._api().call("POST", self._gw_path("/sync"))
        after = inventory_signature(self._api().call("GET", self._gw_path("/inventory")))
        self.inventory_diff = diff_signatures(self.snapshot, after)
        if self.inventory_diff:
            raise obs.GateError(
                f"inventory differs from the pre-run snapshot: {self.inventory_diff}"
            )
        return {"equal_to_snapshot": True}

    # ---- infra additions (shared helpers reused from the observe gate)
    def s_import_api(self) -> dict[str, Any]:
        out = self.import_api()
        for i, member in enumerate(MEMBER_IDS):
            self.rest(
                "PUT",
                f"{self.apim_id}/backends/{member}",
                {
                    "properties": {
                        "url": f"{self.foundry_endpoint.rstrip('/')}/openai",
                        "protocol": "http",
                        "description": f"G17 pool member {i}",
                    }
                },
                obs.APIM_API_VERSION,
            )
        self.rest(
            "PUT",
            f"{self.apim_id}/backends/{POOL_ID}",
            {
                "properties": {
                    "type": "Pool",
                    "description": "G17 pool",
                    "pool": {
                        "services": [
                            {"id": f"{self.apim_id}/backends/{m}", "weight": w, "priority": 1}
                            for m, w in zip(MEMBER_IDS, (100, 0), strict=True)
                        ]
                    },
                }
            },
            obs.APIM_API_VERSION,
        )
        self.rest(
            "PUT",
            f"{self.apim_id}/namedValues/g17-audience",
            {"properties": {"displayName": "g17-audience", "value": self.mcp_audience}},
            obs.APIM_API_VERSION,
        )
        return {**out, "pool": POOL_ID, "members": list(MEMBER_IDS)}

    def run_steps(self) -> None:
        self._load_state()
        step = self.step
        step(
            "provision",
            "create resource group, workspace and a Standard v2 APIM (billable)",
            lambda: self._provision(),
        )
        step("diagnostics", "enable GatewayLogs/GatewayLlmLogs", self.diagnostics)
        step(
            "import-api", "import the Foundry API and a two-member backend pool", self.s_import_api
        )
        step("rbac", "grant OpenAI User on the shared Foundry resource", self._rbac)
        step("register", "register the throwaway APIM (observe)", self.s_register)
        step("snapshot", "take the pre-run inventory snapshot", self.s_snapshot)
        step("mode-manage", "switch the gateway to manage (preflight)", self.s_mode)
        step("grant-publish", "publish a Grant", self.s_grant_publish)
        step("backend-swap", "shift pool weight to canary", self.s_swap)
        step("cap-change", "lower the grant token cap", self.s_cap)
        step("mcp-publish", "publish the MCP server", self.s_mcp_publish)
        step("mcp-call", "call the MCP server with an Entra token", self.s_mcp_call)
        step(
            "unpublish",
            "unpublish MCP (deny, remove), grant; restore swap and cap",
            self.s_unpublish,
        )
        step("inventory-diff", "assert the inventory equals the snapshot", self.s_inventory_diff)

    def _provision(self) -> dict[str, Any]:
        out = self.create_infra()
        return out

    def _rbac(self) -> dict[str, Any]:
        self.approve_rbac = True  # the step approval IS the RBAC approval
        return self.grant_rbac()

    # ---- teardown through the register guard, always attempted
    def run_teardown(self) -> int:
        self.events.append("teardown")
        if self.keep:
            self.phases.append({"phase": "teardown", "status": "skipped_keep", "duration_s": 0.0})
            return 0
        if not self.rg_created and not self.register.items:
            self.phases.append({"phase": "teardown", "status": "nothing_to_do", "duration_s": 0.0})
            return 0
        start = self.clock()
        try:
            detail = self.teardown()
            self.phases.append(
                {
                    "phase": "teardown",
                    "status": "pass",
                    "duration_s": round(self.clock() - start, 1),
                    **detail,
                }
            )
            return 0
        except obs.TeardownRefusedError as exc:
            self.facts["orphans"] = exc.orphans
            self.phases.append(
                {
                    "phase": "teardown",
                    "status": "fail",
                    "untagged_resources": exc.untagged,
                    "orphans": exc.orphans,
                }
            )
        except obs.GateError as exc:
            self.facts["orphans"] = [self.rg_id]
            self.phases.append({"phase": "teardown", "status": "fail", "error": str(exc)[:300]})
        return 3


# --------------------------------------------------------------------------- run + evidence


def run_gate(gate: ManageGate) -> tuple[int, dict[str, Any]]:
    try:
        gate.run_steps()
    finally:
        teardown_code = gate.run_teardown()
    statuses = [p["status"] for p in gate.phases if p["phase"] != "teardown"]
    ran = any(s in ("pass", "fail") for s in statuses)
    if any(s == "fail" for s in statuses):
        result = "FAIL"
    elif any(s == "skipped_awaiting_operator" for s in statuses) or len(
        [p for p in gate.phases if p["status"] == "pass"]
    ) < len(STEPS):
        result = RESULT_OPEN
    else:
        result = "PASS"
    code = 3 if teardown_code else (0 if result == "PASS" else (1 if result == "FAIL" else 2))
    return code, build_evidence(gate, result, ran)


def build_evidence(gate: ManageGate, result: str, ran: bool) -> dict[str, Any]:
    return {
        "gate": GATE,
        "side": "manage",
        "script_version": SCRIPT_VERSION,
        "run_at": obs._utcnow().isoformat(),  # pyright: ignore[reportPrivateUsage]
        "result": result,
        "ran_live_steps": ran,
        "cloud": "commercial",
        "subscription": gate.subscription,
        "location": gate.location,
        "resource_group": gate.resource_group,
        "apim_resource_id": gate.apim_id,
        "tier": "standard_v2",
        "gateway_mode_path": "action executor (gateway_mode_change intent)",
        "intents": gate.intents,
        "credential_check": gate.credential_check,
        "pre_run_inventory": {k: len(v) for k, v in gate.snapshot.items()},
        "inventory_diff": gate.inventory_diff,
        "phases": gate.phases,
        "register": [
            {"id": i.resource_id, "kind": i.kind, "ownership": i.ownership}
            for i in gate.register.items
        ],
        "orphans": gate.facts.get("orphans", []),
        "tokens": TOKEN_REDACTED,
        "reused_loom_apim_manage_target": False,
    }


def render_markdown(ev: dict[str, Any]) -> str:
    lines = [
        f"# G17 APIM manage live run: {ev['result']}",
        "",
        f"- Run at: {ev['run_at']}",
        f"- Cloud: {ev['cloud']}; location: {ev['location']}; tier: {ev['tier']}",
        f"- Mode switch and every change via: {ev['gateway_mode_path']}",
        f"- Credentials stripped at MCP backend: {ev.get('credential_check') or 'not run'}",
        f"- Inventory equals pre-run snapshot: {ev.get('inventory_diff') == {}}",
        f"- Tokens: {ev['tokens']}",
        "",
        "| Phase | Status | Duration (s) |",
        "|---|---|---|",
    ]
    for p in ev["phases"]:
        lines.append(f"| {p['phase']} | {p['status']} | {p.get('duration_s', 0)} |")
    if ev.get("orphans"):
        lines += ["", "Orphans (remove manually): " + ", ".join(ev["orphans"])]
    lines += ["", "Redactions: " + "; ".join(ev.get("redactions", []))]
    return "\n".join(lines) + "\n"


def write_evidence(
    ev: dict[str, Any],
    out_dir: Path,
    *,
    secrets: list[str] | None = None,
    hosts: list[str] | None = None,
) -> Path:
    """Write manage-<stamp>.{json,md}; subscription tokenised, any known secret redacted."""
    tenants = [s for s in (secrets or []) if s]
    clean = obs.redact(
        ev, subscriptions=[ev.get("subscription", "")], secrets=tenants, hosts=hosts or []
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = obs._stamp(obs._utcnow())  # pyright: ignore[reportPrivateUsage]
    base = out_dir / f"manage-{stamp}"
    base.with_suffix(".json").write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(render_markdown(clean), encoding="utf-8")
    return base.with_suffix(".md")


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="G17 APIM manage live gate (operator-approved).")
    ap.add_argument("--subscription", required=True, help="Commercial subscription id (guid)")
    ap.add_argument("--location", default=obs.DEFAULT_LOCATION)
    ap.add_argument("--foundry-endpoint", default="", help="https URL of the approved Foundry")
    ap.add_argument("--foundry-deployment", default="")
    ap.add_argument("--resource-group", default=f"ns-g17m-{obs._stamp(obs._utcnow()).lower()}")  # pyright: ignore[reportPrivateUsage]
    ap.add_argument("--api-url", default="", help="running NeuroSphere API base URL")
    ap.add_argument("--api-token-env", default="NS_G17_API_TOKEN")
    ap.add_argument("--approver-token-env", default="NS_G17_APPROVER_TOKEN")
    ap.add_argument("--domain", default="", help="domain id the gateway is registered under")
    ap.add_argument("--grant-entity-id", default="", help="catalog Grant entity id")
    ap.add_argument("--mcp-entity-id", default="", help="catalog McpServer entity id")
    ap.add_argument("--mcp-backend-url", default="", help="throwaway streamable-HTTP echo backend")
    ap.add_argument("--mcp-audience", default="", help="Entra audience (App ID URI) of the MCP API")
    ap.add_argument(
        "--cap-original-tpm",
        type=int,
        default=1000,
        help="tokens-per-minute the grant fragment has before the gate (restored after)",
    )
    ap.add_argument("--budget-minutes", type=int, default=30)
    ap.add_argument("--approve-step", action="append", default=[], choices=STEPS)
    ap.add_argument("--approve-all-steps", action="store_true")
    ap.add_argument("--state-file", default="", help="resume file (default: none)")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--print-echo-server", action="store_true")
    ap.add_argument("--publisher-email", default="g17-gate@example.com")
    ap.add_argument("--evidence-dir", default=str(REPO / "docs" / "evidence" / "G17"))
    ap.add_argument("--allow-external-evidence-dir", action="store_true")
    return ap


def main(
    argv: list[str] | None = None,
    *,
    runner: obs.AzRunner | None = None,
    api: ApiClient | None = None,
    arm_reader: ArmReader | None = None,
    mcp_caller: McpCaller | None = None,
) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(REFUSAL, file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    if args.print_echo_server:
        print(ECHO_SERVER_SOURCE)
        return 0
    if obs.is_government_location(args.location):
        print(
            "REFUSED: G17 manage is Commercial only; Government is OPEN (no subscription, v2 tiers "
            "unverified, manage mode disabled). No az command was run.",
            file=sys.stderr,
        )
        return 2
    missing = [
        n
        for n in (
            "foundry_endpoint",
            "foundry_deployment",
            "domain",
            "grant_entity_id",
            "mcp_entity_id",
            "mcp_backend_url",
            "mcp_audience",
        )
        if not getattr(args, n)
    ]
    if api is None and not args.api_url:
        missing.append("api_url")
    if missing:
        print(
            f"REFUSED: missing required inputs: {', '.join(missing)}. Nothing changed.",
            file=sys.stderr,
        )
        return 2
    for label, url in (
        ("--foundry-endpoint", args.foundry_endpoint),
        ("--mcp-backend-url", args.mcp_backend_url),
    ):
        if urlparse(url).scheme != "https":
            print(f"REFUSED: {label} must be an https URL.", file=sys.stderr)
            return 2
    try:
        out_dir = obs.evidence_dir_for(
            args.evidence_dir, allow_external=args.allow_external_evidence_dir
        )
    except obs.EvidenceDirRefusedError as exc:
        print(f"REFUSED: {exc}. No az command was run.", file=sys.stderr)
        return 2
    if runner is None:
        az_path = shutil.which("az")
        if not az_path:
            print("REFUSED: the Azure CLI (az) was not found on PATH.", file=sys.stderr)
            return 2
        runner = obs.SubprocessAzRunner(az_path)
    cloud = runner(["cloud", "show", "--query", "name", "-o", "tsv"])
    if cloud.rc != 0 or cloud.stdout.strip() != "AzureCloud":
        print("REFUSED: az is not signed in to the AzureCloud (Commercial) cloud.", file=sys.stderr)
        return 2
    gate = ManageGate(
        run_az=runner,
        subscription=args.subscription,
        location=args.location,
        resource_group=args.resource_group,
        foundry_endpoint=args.foundry_endpoint,
        foundry_deployment=args.foundry_deployment,
        budget_minutes=args.budget_minutes,
        keep=args.keep,
        purge=args.purge,
        publisher_email=args.publisher_email,
        domain=args.domain,
        grant_entity_id=args.grant_entity_id,
        mcp_entity_id=args.mcp_entity_id,
        mcp_backend_url=args.mcp_backend_url,
        mcp_audience=args.mcp_audience,
        approve_steps=set(args.approve_step),
        approve_all=args.approve_all_steps,
        state_file=Path(args.state_file) if args.state_file else None,
        cap_original_tpm=args.cap_original_tpm,
    )
    if api is None:  # pragma: no cover - live only
        token = os.environ.get(args.api_token_env, "")
        if not token:
            print(
                "REFUSED: the API token environment variable is empty (--api-token-env).",
                file=sys.stderr,
            )
            return 2
        api = HttpApiClient(args.api_url, token, os.environ.get(args.approver_token_env, ""))
    gate.api = api
    gate.arm_reader = arm_reader or AzArmReader(gate)  # pragma: no cover - live default
    gate.mcp_caller = mcp_caller
    code, evidence = run_gate(gate)
    if evidence["ran_live_steps"]:
        path = write_evidence(
            evidence,
            out_dir,
            secrets=[getattr(gate, "_token", ""), gate._key],  # pyright: ignore[reportPrivateUsage]
            hosts=[
                urlparse(args.foundry_endpoint).hostname or "",
                urlparse(args.mcp_backend_url).hostname or "",
            ],
        )
        print(f"{evidence['result']}: wrote {path}")
    else:
        print(f"{evidence['result']}: no live step ran; no evidence written (G17 manage OPEN)")
    if code == 3:
        print(f"ORPHANS (remove manually): {evidence['orphans']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
