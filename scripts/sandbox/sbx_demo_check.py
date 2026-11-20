"""Demo check: every page of the local demo has data behind its API, or a reasoned empty (PRP-71).

    python scripts/sandbox/sbx_demo_check.py [--base-url http://127.0.0.1:8000]
        [--token-file PATH] [--json] [--wait-seconds 120]

Run it against a local stack seeded with ``make demo-up`` (``make demo-check``). It reads
``frontend/src/app/route-manifest.json`` and, for every route, calls the page's backing API as the
seeded operator (the route -> calls map is ``services/api/tests/runtime_routes/manifest_calls.py``,
the SAME file ``tests/integration/real_stack/test_manifest_routes.py`` loads, so there is one map).

Per route:

* ``data``: every call that declares a ``non_empty`` field has it filled in at least one domain;
* ``served``: answered 200 but the map asserts no field (nothing to call empty);
* ``allowed_empty``: empty, and listed in ``demo_expected_empty`` (reason and owning PRP shown);
* anything else fails: ``empty`` (unexplained), ``error`` (a non-200), ``unmapped`` (a manifest
  route with no call map) and ``stale_allow`` (an allow-list entry whose page has data now, or
  names no route; strict, like ``KNOWN_EMPTY``, so a fixed gap cannot linger).

It also reads ``GET /api/v1/admin/system/status`` and fails when the producer store, MCP server or
scan is disabled, the lifecycle route (not part of the status payload) is not up in dry-run, or the
stored feature settings did not load. The detector source and the connector worker roles are
worker environment the API does not report: ``not_reported``. Copilot is ``pending_prp_78`` (neither
pass nor failure) while ``NS_DEMO_COPILOT_MODE`` is ``disabled``. A few demo-world sanity checks
read the catalog and the map (curated agents, the four telemetry-only agents as discovered drafts,
the outage service's downstream agents degraded).

Credentials: the bearer token of the seeded operator is resolved in this order, first hit wins:

1. ``--token-file`` / ``NS_DEMO_CHECK_TOKEN_FILE``;
2. ``NS_STAND_IN_TOKEN_FILE`` (the CI stand-in API's token file);
3. the default for a developer: ``az account get-access-token`` for the API audience (the first of
   ``NS_AUTH_AUDIENCES`` when set, else ``NS_ENTRA_CLIENT_ID``; tenant ``NS_ENTRA_TENANT_ID``), so
   ``make demo-up`` followed by ``make demo-check`` is two commands for an operator who exported
   the two Entra ids and ran ``az login``. The token lives in memory only: it is never written to
   disk, printed, logged, put in ``--json`` output, or echoed in an error (the CLI's stderr is
   never surfaced).

The signed-in user must be granted in the seeded stack (``make demo-up OPERATOR_OID=<object id>``
or ``make grant-operator OPERATOR_OID=<object id>``); an HTTP 401/403 says so.

Loopback only: the API URL (and ``NS_COSMOS_ENDPOINT`` when set) must be a loopback address
written as an IP (``127.0.0.1``, never ``localhost``); there is no override.

Exit 0 only when every route is data-or-allow-listed and no feature is disabled; 1 = the check
failed; 2 = refused (non-loopback endpoint, no token, operator not granted, bad arguments); 3 = the
API is unreachable.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Protocol
from urllib.parse import urlencode, urlparse

_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure):
    _reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (HERE, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from neurosphere_api.actions import customer_control_domain  # noqa: E402
from sbx_guard import GuardError, is_local_host, require_local_endpoint  # noqa: E402

from sandbox.demo.build import DemoWorld, build_demo_world  # noqa: E402

EXIT_FAILED: Final = 1
EXIT_REFUSED: Final = 2
EXIT_UNREACHABLE: Final = 3
MANIFEST: Final = REPO / "frontend" / "src" / "app" / "route-manifest.json"
CALLS_FILE: Final = REPO / "services" / "api" / "tests" / "runtime_routes" / "manifest_calls.py"
DEFAULT_BASE_URL: Final = "http://127.0.0.1:8000"
DEFAULT_WAIT_SECONDS: Final = 120.0
DEFAULT_POLL_SECONDS: Final = 10.0
STATUS_PATH: Final = "/api/v1/admin/system/status"
LIFECYCLE_PATH: Final = "/api/v1/lifecycle/status"
COPILOT_PATH: Final = "/api/v1/copilot/conversations"
DOMAINS_PATH: Final = "/api/v1/me/domains"
ENTITIES_PATH: Final = "/api/v1/catalog/entities"
VIEWPORT_PATH: Final = "/api/v1/map/domains/{domain}/viewport"
MAX_PAGES: Final = 20

#: Expected non-200 answers (same as ``EXPECTED_STATUS`` in ``test_manifest_routes.py``; a unit test
#: keeps the two equal). The demo price sheet may or may not price the demo models, so 200 is
#: accepted for these calls as well.
EXPECTED_STATUS: Final[dict[str, int]] = {
    "/api/v1/finops/domains/{domain}/forecast?history_days=30&horizon_days=30&currency=USD": 409,
}

# Route states.
DATA: Final = "data"
SERVED: Final = "served"
ALLOWED_EMPTY: Final = "allowed_empty"
EMPTY: Final = "empty"
ERROR: Final = "error"
UNMAPPED: Final = "unmapped"
STALE_ALLOW: Final = "stale_allow"
ROUTE_PASS: Final = frozenset({DATA, SERVED, ALLOWED_EMPTY})

# Feature states.
ENABLED: Final = "enabled"
DISABLED: Final = "disabled"
NOT_REPORTED: Final = "not_reported"
PENDING_PRP_78: Final = "pending_prp_78"
UNEXPECTED: Final = "unexpected"
FEATURE_FAIL: Final = frozenset({DISABLED, UNEXPECTED})

# Sanity states.
PASSED: Final = "pass"
FAIL: Final = "fail"
NOT_CHECKED: Final = "not_checked"


@dataclass(frozen=True)
class AllowedEmpty:
    """One reasoned exception: a page that is legitimately empty in the demo world."""

    reason: str
    owner_prp: str


#: Route -> why it is empty on purpose and which PRP will fill it. Strict: an entry whose page has
#: data now fails the check. Empty today: the seeded world is checked by ``KNOWN_EMPTY = {}`` in
#: ``test_manifest_routes.py``; add an entry only after a live ``make demo-check`` shows a gap.
demo_expected_empty: Final[dict[str, AllowedEmpty]] = {}


class CheckError(RuntimeError):
    """The check could not run (no domains, API unreachable). Messages never hold a credential."""


class NotGrantedError(CheckError):
    """The API refused the operator's token (401/403): the user is not granted in the stack."""


GRANT_HINT: Final = (
    "the operator token's user is not granted in the seeded stack (the API answered {status}): "
    "re-run `make demo-up OPERATOR_OID=<your object id>` (or `make grant-operator "
    "OPERATOR_OID=<your object id>`); a token for another audience is refused the same way"
)


@dataclass(frozen=True)
class Reply:
    status: int
    body: Any = None


class Client(Protocol):
    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Reply: ...


@dataclass(frozen=True)
class RouteResult:
    route: str
    state: str
    detail: str = ""
    reason: str = ""
    owner_prp: str = ""

    @property
    def ok(self) -> bool:
        return self.state in ROUTE_PASS


@dataclass(frozen=True)
class FeatureResult:
    name: str
    state: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state not in FEATURE_FAIL


@dataclass(frozen=True)
class SanityResult:
    name: str
    state: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state != FAIL


@dataclass
class Report:
    routes: list[RouteResult] = field(default_factory=list)
    features: list[FeatureResult] = field(default_factory=list)
    sanity: list[SanityResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        rows = (*self.routes, *self.features, *self.sanity)
        return bool(self.routes) and all(r.ok for r in rows)

    def as_json(self) -> dict[str, Any]:
        def rows(items: Sequence[Any]) -> list[dict[str, Any]]:
            return [dict(vars(i)) for i in items]

        return {
            "ok": self.ok,
            "routes": rows(self.routes),
            "features": rows(self.features),
            "sanity": rows(self.sanity),
        }


# -- the shared route -> calls map -----------------------------------------------------------


def load_calls(path: Path = CALLS_FILE) -> ModuleType:
    """The route -> calls map module (loaded by path, as ``test_manifest_routes.py`` does)."""
    spec = importlib.util.spec_from_file_location("ns_demo_check_manifest_calls", path)
    if spec is None or spec.loader is None:
        raise CheckError("the route call map cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_manifest_routes(path: Path = MANIFEST) -> list[str]:
    routes = json.loads(path.read_text(encoding="utf-8"))["routes"]
    return [str(r) for r in routes]


def _key(call: Any) -> str:
    query = urlencode(list(call.query))
    return f"{call.path}?{query}" if query else str(call.path)


def _pluck(body: Any, pointer: Sequence[str | int]) -> Any:
    for step in pointer:
        try:
            body = body[step]
        except (KeyError, IndexError, TypeError):
            return None
    return body


def _has(body: Any, name: str) -> bool:
    return bool(body.get(name)) if isinstance(body, dict) else False


def _reason(reply: Reply) -> str:
    body = reply.body
    reason = body.get("reason") if isinstance(body, dict) else None
    return f" ({reason})" if isinstance(reason, str) and len(reason) < 80 else ""


class CachedClient:
    """Memoizes GETs: every route repeats the shell calls (``/me/domains``) once per domain."""

    def __init__(self, inner: Client) -> None:
        self._inner = inner
        self._seen: dict[tuple[str, tuple[tuple[str, str], ...], str | None], Reply] = {}

    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Reply:
        key = (path, tuple(query), persona)
        if key not in self._seen:
            self._seen[key] = self._inner.get(path, query, persona)
        return self._seen[key]


def discover_domains(client: Client) -> list[str]:
    """The domains the operator reads, minus the reserved customer control domain."""
    reply = client.get(DOMAINS_PATH)
    if reply.status in (401, 403):
        raise NotGrantedError(GRANT_HINT.format(status=reply.status))
    if reply.status != 200 or not isinstance(reply.body, dict):
        raise CheckError(f"GET {DOMAINS_PATH} answered {reply.status}{_reason(reply)}")
    listed = [str(i["domain_id"]) for i in reply.body.get("items", [])]
    domains = [d for d in listed if d != customer_control_domain(*d.split(":")[:2])]
    if not domains:
        raise CheckError(
            "the operator reads no domain: seed the stack and grant the operator "
            "(`make demo-up OPERATOR_OID=<your object id>`)"
        )
    return domains


def _evaluate_route(
    client: Client, route_calls: Sequence[Any], domains: Sequence[str]
) -> tuple[list[str], dict[str, bool]]:
    failures: list[str] = []
    seen: dict[str, bool] = {}
    for domain in domains:
        captured: dict[str, str] = {}
        for call in route_calls:
            if any(need not in captured for need in call.needs):
                continue
            path = str(call.path).replace("{domain}", domain)
            for name, value in captured.items():
                path = path.replace("{" + name + "}", value)
            reply = client.get(path, call.query, call.as_persona)
            expected = EXPECTED_STATUS.get(_key(call))
            if expected is not None:
                if reply.status not in (expected, 200):
                    failures.append(f"{path}: HTTP {reply.status}, expected {expected}")
                continue
            if reply.status != 200:
                failures.append(f"{path}: HTTP {reply.status}{_reason(reply)}")
                continue
            for name, pointer in call.capture:
                value = _pluck(reply.body, pointer)
                if isinstance(value, str) and name not in captured:
                    captured[name] = value
            if call.non_empty is not None:
                key = _key(call)
                seen[key] = seen.get(key, False) or _has(reply.body, call.non_empty)
    return failures, seen


def check_routes(
    client: Client,
    manifest_routes: Sequence[str],
    calls: Mapping[str, Sequence[Any]],
    domains: Sequence[str],
    allow: Mapping[str, AllowedEmpty],
) -> list[RouteResult]:
    """One result per manifest route, plus one per allow-list entry that names no route."""
    results: list[RouteResult] = []
    for route in manifest_routes:
        entry = allow.get(route)
        reason, owner = (entry.reason, entry.owner_prp) if entry else ("", "")
        route_calls = calls.get(route)
        if route_calls is None:
            results.append(
                RouteResult(route, UNMAPPED, "no entry in the route call map (manifest_calls.py)")
            )
            continue
        failures, seen = _evaluate_route(client, route_calls, domains)
        if failures:
            results.append(RouteResult(route, ERROR, "; ".join(failures[:3])))
            continue
        empty = sorted(k for k, ok in seen.items() if not ok)
        if empty:
            state = ALLOWED_EMPTY if entry else EMPTY
            results.append(
                RouteResult(
                    route,
                    state,
                    "empty in every readable domain: " + ", ".join(empty),
                    reason,
                    owner,
                )
            )
        elif entry:
            why = "now has data" if seen else "the call map asserts no field to call it empty"
            results.append(
                RouteResult(
                    route, STALE_ALLOW, f"allow-listed as empty but {why}: remove it", reason, owner
                )
            )
        else:
            results.append(RouteResult(route, DATA if seen else SERVED))
    for route in sorted(set(allow) - set(manifest_routes)):
        results.append(
            RouteResult(route, STALE_ALLOW, "allow-listed but not a manifest route: remove it")
        )
    return results


# -- feature status --------------------------------------------------------------------------

#: Feature -> status-payload component. ``lifecycle`` and the two worker features are handled
#: separately (see :func:`check_features`).
COMPONENT_FEATURES: Final = (
    ("producer_store", "admin_producers"),
    ("mcp_server", "mcp_server"),
    ("scan", "scan"),
)


def _components(body: Any) -> dict[str, str]:
    items = body.get("components", []) if isinstance(body, dict) else []
    return {str(c.get("name")): str(c.get("state")) for c in items if isinstance(c, dict)}


def check_features(client: Client, copilot_mode: str) -> list[FeatureResult]:
    status = client.get(STATUS_PATH)
    if status.status != 200 or not isinstance(status.body, dict):
        return [
            FeatureResult(
                "system_status",
                UNEXPECTED,
                f"GET {STATUS_PATH} answered {status.status}{_reason(status)}",
            )
        ]
    components = _components(status.body)
    results: list[FeatureResult] = []
    for feature, component in COMPONENT_FEATURES:
        state = components.get(component, "absent")
        results.append(
            FeatureResult(
                feature, ENABLED if state == "ok" else DISABLED, f"component {component}: {state}"
            )
        )
    results.append(_lifecycle(client))
    results.append(
        FeatureResult(
            "detector_archive_source",
            NOT_REPORTED,
            "NS_WORKER_REC_SOURCE is worker environment; no API field reports it "
            "(the recommendations pages above prove the detector output)",
        )
    )
    results.append(
        FeatureResult(
            "connector_roles",
            NOT_REPORTED,
            "connector worker roles run in the workers container; the status payload lists API "
            "components only",
        )
    )
    stored = status.body.get("stored_settings")
    stored = stored if isinstance(stored, dict) else {}
    loaded = stored.get("status") == "loaded" and not stored.get("invalid_keys")
    results.append(
        FeatureResult(
            "stored_settings",
            ENABLED if loaded else DISABLED,
            f"stored_settings.status: {stored.get('status')}; "
            f"invalid_keys: {len(stored.get('invalid_keys') or [])}",
        )
    )
    results.append(_copilot(client, copilot_mode, components.get("copilot", "absent")))
    return results


def _lifecycle(client: Client) -> FeatureResult:
    """Lifecycle installs no status component; its own status route answers 503 when unbuilt."""
    reply = client.get(LIFECYCLE_PATH)
    mode = reply.body.get("mode") if isinstance(reply.body, dict) else None
    if reply.status == 200 and mode == "dry_run":
        return FeatureResult("lifecycle", ENABLED, f"{LIFECYCLE_PATH}: mode dry_run")
    if reply.status == 200:
        return FeatureResult("lifecycle", UNEXPECTED, f"{LIFECYCLE_PATH}: mode {mode}, not dry_run")
    return FeatureResult("lifecycle", DISABLED, f"{LIFECYCLE_PATH}: HTTP {reply.status}")


def _copilot(client: Client, mode: str, component: str) -> FeatureResult:
    if mode != "disabled":
        state = ENABLED if component == "ok" else DISABLED
        return FeatureResult("copilot", state, f"mode {mode}; component copilot: {component}")
    reply = client.get(COPILOT_PATH)
    shape = reply.status == 503 and (
        isinstance(reply.body, dict) and reply.body.get("reason") == "copilot_unconfigured"
    )
    if not shape:
        return FeatureResult(
            "copilot",
            UNEXPECTED,
            f"NS_DEMO_COPILOT_MODE is disabled but {COPILOT_PATH} answered {reply.status}"
            f"{_reason(reply)}, not 503 copilot_unconfigured",
        )
    return FeatureResult(
        "copilot",
        PENDING_PRP_78,
        "disabled by design until PRP-78 ships the recorded mode; routes answer 503 "
        "copilot_unconfigured",
    )


# -- demo-world sanity -----------------------------------------------------------------------


def _slug(identifier: str) -> str:
    return identifier.rsplit(":", 1)[-1]


def _entities(client: Client, extra: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        query = [*extra, ("page_size", "200")]
        if cursor:
            query.append(("cursor", cursor))
        reply = client.get(ENTITIES_PATH, query)
        if reply.status != 200 or not isinstance(reply.body, dict):
            raise CheckError(f"GET {ENTITIES_PATH} answered {reply.status}{_reason(reply)}")
        items.extend(i for i in reply.body.get("items", []) if isinstance(i, dict))
        cursor = reply.body.get("next_cursor")
        if not cursor:
            break
    return items


def _ids(entities: Sequence[dict[str, Any]]) -> set[str]:
    return {_slug(str(e.get("id") or e.get("canonical_id") or "")) for e in entities}


def _agent_health(client: Client, domains: Sequence[str]) -> dict[str, str]:
    """Agent slug -> health from the map viewport (every domain)."""
    health: dict[str, str] = {}
    for domain in domains:
        reply = client.get(VIEWPORT_PATH.replace("{domain}", domain), (("node_budget", "2000"),))
        if reply.status != 200 or not isinstance(reply.body, dict):
            continue
        for node in reply.body.get("nodes", []):
            if not isinstance(node, dict) or node.get("kind") not in ("agent", "sub_agent"):
                continue
            metrics = node.get("metrics")
            state = metrics.get("health") if isinstance(metrics, dict) else None
            health[_slug(str(node.get("id", "")))] = str(state or "unknown")
    return health


def check_world(
    client: Client,
    domains: Sequence[str],
    world: DemoWorld,
    *,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[SanityResult]:
    curated = {_slug(str(a["id"])) for a in world.agents}
    undeclared = {_slug(a.agent_id) for a in world.undeclared_agents}
    results: list[SanityResult] = []
    try:
        present = _ids(_entities(client, (("entity_type", "agent"),)))
        drafts = _ids(_entities(client, (("entity_type", "agent"), ("lifecycle", "draft"))))
    except CheckError as exc:
        reason = str(exc)
        return [
            SanityResult("curated_agents_present", FAIL, reason),
            SanityResult("undeclared_agents_discovered", FAIL, reason),
            SanityResult("outage_downstream_health", NOT_CHECKED, "the catalog was unreadable"),
        ]
    missing = sorted(curated - present)
    results.append(
        SanityResult(
            "curated_agents_present",
            FAIL if missing else PASSED,
            f"missing: {', '.join(missing[:6])}"
            if missing
            else f"{len(curated)} of {len(curated)}",
        )
    )
    absent = sorted(undeclared - drafts)
    results.append(
        SanityResult(
            "undeclared_agents_discovered",
            FAIL if absent else PASSED,
            f"not discovered as drafts: {', '.join(absent)}"
            if absent
            else f"{len(undeclared)} telemetry-only agents are draft catalog agents",
        )
    )
    results.append(_outage_domain_errors(client, world, wait_seconds, poll_seconds, sleep, clock))
    # The bounded wait was spent above. Per-agent health is only on the map once its topology
    # backend carries metrics (PRP-74); until then the viewport answers "unknown" and this row
    # stays not_checked.
    results.append(_outage_health(client, domains, world, 0.0, poll_seconds, sleep, clock))
    return results


ERRORS_PATH: Final = "/api/v1/dashboards/domains/{domain}/errors"
#: The API's "degraded" threshold (``health_degraded_error_rate``): an affected domain's worst
#: hour must reach it, an unaffected domain's worst hour must stay under it.
DOMAIN_ERROR_RATE: Final = 0.05


def _worst_hourly_error_rate(client: Client, domain: str) -> tuple[float | None, str]:
    """Highest hourly error rate over the last two days, and the aggregates watermark."""
    reply = client.get(ERRORS_PATH.replace("{domain}", domain), (("days", "2"), ("grain", "hour")))
    if reply.status != 200 or not isinstance(reply.body, dict):
        return None, ""
    freshness = reply.body.get("freshness")
    watermark = str(freshness.get("watermark") or "") if isinstance(freshness, dict) else ""
    worst: float | None = None
    for series in reply.body.get("series", []):
        if not isinstance(series, dict) or series.get("key") != "error_rate":
            continue
        for point in series.get("points", []):
            value = _pluck(point, ("value", "value"))
            if isinstance(value, int | float):
                worst = max(worst or 0.0, float(value))
    return worst, watermark


def _outage_domain_errors(
    client: Client,
    world: DemoWorld,
    wait_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> SanityResult:
    """The incident as the aggregates show it, at domain grain (the grain the API serves).

    Domains holding a downstream agent of the failing service must show an hour at or above the
    degraded error rate; a domain with no downstream agent must not. Per-agent health is the
    map's job (``outage_downstream_health``).
    """
    name = "outage_domain_error_rate"
    downstream = set(world.downstream_agent_ids)
    affected = sorted({str(a["domain_id"]) for a in world.agents if a["id"] in downstream})
    calm = sorted({str(a["domain_id"]) for a in world.agents} - set(affected))
    if not affected or not calm:
        return SanityResult(name, NOT_CHECKED, "the world has no affected/unaffected domain split")
    deadline = clock() + wait_seconds
    while True:  # bounded: the aggregates role drains in event order, the incident hour last
        rates = {d: _worst_hourly_error_rate(client, d) for d in (*affected, *calm)}
        watermark = max((w for _, w in rates.values()), default="")
        noisy = sorted(_slug(d) for d in calm if (rates[d][0] or 0.0) >= DOMAIN_ERROR_RATE)
        if noisy:
            return SanityResult(
                name, FAIL, f"unaffected domain(s) show an error hour: {', '.join(noisy)}"
            )
        quiet = sorted(_slug(d) for d in affected if (rates[d][0] or 0.0) < DOMAIN_ERROR_RATE)
        if not quiet:
            return SanityResult(
                name,
                PASSED,
                f"{len(affected)} affected domain(s) reach {DOMAIN_ERROR_RATE:.2f}; "
                f"{len(calm)} unaffected stay under it",
            )
        if clock() >= deadline:
            return SanityResult(
                name,
                NOT_CHECKED,
                f"no error hour yet in: {', '.join(quiet)} after {wait_seconds:.0f}s "
                f"(aggregates watermark {watermark or 'unknown'}; the incident hour drains last)",
            )
        sleep(poll_seconds)


def _outage_health(
    client: Client,
    domains: Sequence[str],
    world: DemoWorld,
    wait_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> SanityResult:
    name = "outage_downstream_health"
    downstream = {_slug(i) for i in world.downstream_agent_ids}
    unrelated = {_slug(i) for i in world.unrelated_agent_ids}
    deadline = clock() + wait_seconds
    while True:  # bounded: the aggregates role needs time to materialise health
        health = _agent_health(client, domains)
        bad = {"degraded", "failing"}
        down_ok = {s for s in downstream if health.get(s) in bad}
        calm = {s for s in unrelated if health.get(s) not in (None, *bad)}
        if not health or not any(
            health.get(s, "unknown") != "unknown" for s in downstream | unrelated
        ):
            verdict = None  # nothing materialised yet (or the map has no agent nodes)
        elif down_ok == downstream and calm:
            return SanityResult(
                name,
                PASSED,
                f"{len(downstream)} downstream degraded/failing; {len(calm)} others not",
            )
        else:
            verdict = SanityResult(
                name,
                FAIL,
                "downstream not degraded: "
                + (", ".join(sorted(downstream - down_ok)) or "none")
                + f"; unrelated agents not degraded: {len(calm)}",
            )
        if clock() >= deadline:
            if verdict is not None:
                return verdict
            return SanityResult(
                name,
                NOT_CHECKED,
                "the map reports no agent health (unknown for every agent) after "
                f"{wait_seconds:.0f}s: the health source has not materialised",
            )
        sleep(poll_seconds)


# -- guards and the HTTP client --------------------------------------------------------------


def require_loopback_url(url: str) -> str:
    """The API URL must be an http(s) loopback IP: ``127.0.0.1``, never ``localhost``."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host == "localhost" or not is_local_host(host):
        raise GuardError(
            f"refusing API host {host!r}: only a loopback address written as an IP "
            "(127.0.0.1) is allowed; there is no override"
        )
    return url.rstrip("/")


def guard_environment(base_url: str, environ: Mapping[str, str]) -> str:
    """Refuse anything that is not the local stack. Returns the approved base URL."""
    if environ.get("NS_ENV", "local") != "local":
        raise GuardError("the demo check only runs with NS_ENV=local")
    cosmos = environ.get("NS_COSMOS_ENDPOINT")
    if cosmos:
        require_local_endpoint(cosmos)
    return require_loopback_url(base_url)


TokenProvider = Callable[[Mapping[str, str]], str]

AZ_HINT: Final = (
    "no operator token: export NS_ENTRA_TENANT_ID and NS_ENTRA_CLIENT_ID (the ids `make demo-up` "
    "used) and run `az login`, or pass --token-file / set NS_DEMO_CHECK_TOKEN_FILE"
)


def az_command(exe: str) -> list[str]:
    """The argv prefix that runs ``az`` (as ``scripts/gates/p29_entra_local.py`` does).

    On Windows ``az`` is ``az.cmd``; run its bundled ``python.exe -IBm azure.cli`` directly so no
    cmd.exe argument parsing is involved.
    """
    path = Path(exe)
    if path.suffix.lower() in {".cmd", ".bat"}:
        bundled = path.parent.parent / "python.exe"
        if bundled.is_file():
            return [str(bundled), "-IBm", "azure.cli"]
    return [exe]


def api_audience(environ: Mapping[str, str]) -> str:
    """The audience the API accepts: the first ``NS_AUTH_AUDIENCES`` entry, else the client id."""
    listed = [a.strip() for a in (environ.get("NS_AUTH_AUDIENCES") or "").split(",") if a.strip()]
    return listed[0] if listed else (environ.get("NS_ENTRA_CLIENT_ID") or "").strip()


def az_token(
    environ: Mapping[str, str],
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
) -> str:
    """Ask the Azure CLI for an access token for the API audience. In memory only.

    Never surfaces the CLI's stderr or stdout in an error (either could carry a credential).
    """
    tenant = (environ.get("NS_ENTRA_TENANT_ID") or "").strip()
    audience = api_audience(environ)
    if not tenant or not audience:
        raise GuardError(AZ_HINT)
    exe = which("az")
    if exe is None:
        raise GuardError("the Azure CLI (az) was not found on PATH; " + AZ_HINT)
    argv = [
        *az_command(exe),
        "account",
        "get-access-token",
        "--resource",
        audience,
        "--tenant",
        tenant,
        "--query",
        "accessToken",
        "--output",
        "tsv",
    ]
    try:
        done = run(argv, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        raise GuardError("the Azure CLI could not be run; " + AZ_HINT) from None
    token = (done.stdout or "").strip() if done.returncode == 0 else ""
    if not token:
        raise GuardError("the Azure CLI returned no token (is `az login` current?); " + AZ_HINT)
    return token


def resolve_token(
    path: str | None, environ: Mapping[str, str], provider: TokenProvider | None = None
) -> str:
    """Token file (flag or env), then the CI stand-in's file, then the Azure CLI. First hit wins."""
    chosen = (
        path or environ.get("NS_DEMO_CHECK_TOKEN_FILE") or environ.get("NS_STAND_IN_TOKEN_FILE")
    )
    if not chosen:
        return (provider or az_token)(environ)
    try:
        token = Path(chosen).read_text(encoding="utf-8").strip()
    except OSError:
        raise GuardError("the operator token file cannot be read") from None
    if not token:
        raise GuardError("the operator token file is empty")
    return token


class HttpClient:
    """Plain GETs with the operator's bearer token. The token is never part of any output."""

    def __init__(self, base_url: str, token: str) -> None:
        import httpx

        self._http = httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30.0
        )

    def __repr__(self) -> str:
        return "HttpClient(<loopback>)"

    def get(
        self, path: str, query: Sequence[tuple[str, str]] = (), persona: str | None = None
    ) -> Reply:
        import httpx

        try:
            response = self._http.get(path, params=list(query))
        except httpx.HTTPError as exc:
            raise CheckError(f"the API is unreachable ({type(exc).__name__})") from None
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        return Reply(response.status_code, body)

    def close(self) -> None:
        self._http.close()


# -- run and render --------------------------------------------------------------------------


def run_checks(
    client: Client,
    *,
    copilot_mode: str,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    allow: Mapping[str, AllowedEmpty] | None = None,
    manifest_routes: Sequence[str] | None = None,
    calls: Mapping[str, Sequence[Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Report:
    cached = CachedClient(client)
    domains = discover_domains(cached)
    report = Report()
    report.routes = check_routes(
        cached,
        manifest_routes if manifest_routes is not None else load_manifest_routes(),
        calls if calls is not None else load_calls().MANIFEST_CALLS,
        domains,
        demo_expected_empty if allow is None else allow,
    )
    report.features = check_features(client, copilot_mode)
    report.sanity = check_world(
        client,
        domains,
        build_demo_world("commercial"),
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
        sleep=sleep,
        clock=clock,
    )
    return report


def render(report: Report) -> str:
    lines: list[str] = []

    def table(title: str, rows: Sequence[tuple[str, str, str, bool]]) -> None:
        width = max((len(r[0]) for r in rows), default=4)
        lines.append(f"\n{title}")
        for name, state, detail, ok in rows:
            mark = "ok  " if ok else "FAIL"
            lines.append(f"  {mark} {name:<{width}}  {state:<15} {detail}".rstrip())

    def route_detail(r: RouteResult) -> str:
        if r.state == ALLOWED_EMPTY:
            return f"{r.reason} (owner {r.owner_prp})"
        return r.detail

    table("Routes", [(r.route, r.state, route_detail(r), r.ok) for r in report.routes])
    table("Features", [(f.name, f.state, f.detail, f.ok) for f in report.features])
    table("Demo world", [(s.name, s.state, s.detail, s.ok) for s in report.sanity])
    failed = sum(not r.ok for r in (*report.routes, *report.features, *report.sanity))
    # A row that could not be checked or is pending is not a failure, but it is not a pass either:
    # the banner counts it so a clean exit never reads as "everything was verified".
    open_states = (NOT_CHECKED, NOT_REPORTED, PENDING_PRP_78)
    unverified = sum(r.state in open_states for r in (*report.features, *report.sanity))
    suffix = f", {unverified} not verified (see the rows above)" if unverified else ""
    lines.append(f"\n{'PASS' if report.ok else 'FAIL'}: {failed} failing row(s){suffix}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", help=f"API base URL (default {DEFAULT_BASE_URL})")
    parser.add_argument(
        "--token-file",
        help="file holding the operator's bearer token (default: NS_DEMO_CHECK_TOKEN_FILE, then "
        "NS_STAND_IN_TOKEN_FILE, then a token from `az account get-access-token`, kept in memory)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    return parser


ClientFactory = Callable[[str, str], Client]


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    token_provider: TokenProvider | None = None,
) -> int:
    environ = os.environ if env is None else env
    args = _parser().parse_args(argv)
    try:
        base = guard_environment(
            args.base_url or environ.get("NS_DEMO_CHECK_API_URL") or DEFAULT_BASE_URL, environ
        )
        token = resolve_token(args.token_file, environ, token_provider)
    except GuardError as exc:
        print(f"sbx_demo_check: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    client = (client_factory or HttpClient)(base, token)
    try:
        report = run_checks(
            client,
            copilot_mode=environ.get("NS_DEMO_COPILOT_MODE") or "disabled",
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except NotGrantedError as exc:
        print(f"sbx_demo_check: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except CheckError as exc:
        print(f"sbx_demo_check: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    print(json.dumps(report.as_json(), indent=2, sort_keys=True) if args.json else render(report))
    return 0 if report.ok else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
