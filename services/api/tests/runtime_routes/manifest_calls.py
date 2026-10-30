"""The API calls behind every page of ``frontend/src/app/route-manifest.json`` (PRP-29 item 11).

One source of truth for two suites: the CI-safe in-memory suite (``test_manifest_routes_serve.py``)
and the emulator suite (``tests/integration/real_stack/test_manifest_routes.py``, which loads this
file by path). Each entry is derived from the frontend api modules (``frontend/src/features/*/
hooks.ts``, ``paths.ts``, ``overview/data.ts``, ``app/domain.tsx``); the route list is checked
against the manifest by a test, so a new page cannot be added without its calls.

Only the GETs a page issues while rendering are listed (mutations need a user action). Two kinds
of call are out of scope here and listed in :data:`NOT_COVERED_OVER_HTTP`.

Path templates use ``{domain}`` (a readable domain id) and ``{<name>}`` placeholders filled from an
earlier call's response through ``capture`` (the id a list page links to, exactly what the page's
detail route is opened with).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "COPILOT_ROUTES_503",
    "DOMAINS_CALL",
    "MANIFEST_CALLS",
    "NOT_COVERED_OVER_HTTP",
    "ApiCall",
]

#: Pointer into a JSON body: dict keys and list indexes, e.g. ``("items", 0, "id")``.
Pointer = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class ApiCall:
    """One ``GET`` a page makes. ``path`` may hold ``{domain}`` and captured-id placeholders."""

    path: str
    query: tuple[tuple[str, str], ...] = ()
    #: ``name -> pointer``: values to take from this response for later calls of the same route.
    capture: tuple[tuple[str, Pointer], ...] = ()
    #: The body field that must be a non-empty list/object for "the page has data" (real stack).
    non_empty: str | None = None
    #: Placeholders this call needs (filled from earlier captures); a call whose placeholder has no
    #: captured value is skipped by the real-stack suite and requested with ``unknown`` in CI.
    needs: tuple[str, ...] = field(default=())
    #: Persona slug (``sandbox/stack/personas.json``) the real-stack suite requests as; reports are
    #: private to their owner (the seed owns them as ``analyst``), so a human operator lists none.
    as_persona: str | None = None


def q(**params: str | int) -> tuple[tuple[str, str], ...]:
    return tuple((k, str(v)) for k, v in params.items())


DOMAINS_CALL: Final = ApiCall("/api/v1/me/domains", non_empty="items")

_SHELL: Final = (DOMAINS_CALL,)

_COST: Final = "/api/v1/dashboards/domains/{domain}/cost"
_REVIEW: Final = "/api/v1/review/domains/{domain}/items"
_INTENTS: Final = "/api/v1/actions/domains/{domain}/intents"
_VIEWPORT: Final = "/api/v1/map/domains/{domain}/viewport"
_REPORTS: Final = "/api/v1/reports/domains/{domain}/reports"
_EMERGENCY: Final = ApiCall("/api/v1/actions/emergency-disable")


def _dashboard(metric: str) -> tuple[ApiCall, ...]:
    return (
        *_SHELL,
        ApiCall(
            f"/api/v1/dashboards/domains/{{domain}}/{metric}",
            q(days=30, grain="day"),
            non_empty="series",
        ),
    )


def _workspace(role: str) -> tuple[ApiCall, ...]:
    return (*_SHELL, ApiCall(f"/api/v1/workspaces/{role}"))


#: Route -> the calls its page makes (shell calls included). Keys equal the manifest exactly.
MANIFEST_CALLS: Final[dict[str, tuple[ApiCall, ...]]] = {
    "/": (
        *_SHELL,
        ApiCall(_COST, q(days=1), non_empty="series"),
        ApiCall(_REVIEW, q(state="pending")),
        ApiCall(_INTENTS, q(state="awaiting_confirmation")),
        ApiCall(_INTENTS, q(state="awaiting_approval")),
        ApiCall(_VIEWPORT, q(node_budget=1), non_empty="coverage"),
        ApiCall(_REPORTS, q(limit=5), as_persona="analyst"),
    ),
    "/actions": (
        *_SHELL,
        ApiCall(_INTENTS, q(limit=25), non_empty="items"),
        _EMERGENCY,
    ),
    "/actions/detail": (
        *_SHELL,
        ApiCall(
            _INTENTS,
            q(limit=25),
            capture=(("intent_id", ("items", 0, "intent", "intent_id")),),
            non_empty="items",
        ),
        ApiCall(_INTENTS + "/{intent_id}", needs=("intent_id",), non_empty="intent"),
        _EMERGENCY,
    ),
    "/actions/propose": (*_SHELL, _EMERGENCY),
    # PRP-34 item 8: the gateways page lists the domain's registered gateways; the catalog
    # publication page lists Grants and MCP servers. Neither is seeded in the stack, so no
    # ``non_empty`` is asserted.
    "/catalog/publication": (
        *_SHELL,
        ApiCall("/api/v1/catalog/entities", q(entity_type="grant")),
        ApiCall("/api/v1/catalog/entities", q(entity_type="mcp_server")),
    ),
    "/gateways": (*_SHELL, ApiCall("/api/v1/gateways/domains/{domain}/gateways")),
    "/dashboards/cost": _dashboard("cost"),
    "/dashboards/coverage": _dashboard("coverage"),
    "/dashboards/latency": _dashboard("latency"),
    "/map": (*_SHELL, ApiCall(_VIEWPORT, q(node_budget=2000), non_empty="nodes")),
    "/map/table": (*_SHELL, ApiCall(_VIEWPORT, non_empty="nodes")),
    "/mcp-admin": (
        *_SHELL,
        ApiCall("/api/v1/mcp/admin/servers", q(limit=25), non_empty="items"),
    ),
    "/mcp-admin/server": (
        *_SHELL,
        ApiCall(
            "/api/v1/mcp/admin/servers",
            q(limit=25),
            capture=(("server_id", ("items", 0, "id")),),
            non_empty="items",
        ),
        ApiCall("/api/v1/mcp/admin/servers/{server_id}", needs=("server_id",), non_empty="id"),
        ApiCall(
            "/api/v1/mcp/admin/servers/{server_id}/tools",
            needs=("server_id",),
            non_empty="server_id",
        ),
    ),
    "/quality": (
        *_SHELL,
        ApiCall("/api/v1/evaluation/domains/{domain}/quality", non_empty="coverage"),
    ),
    "/recommendations": (
        *_SHELL,
        ApiCall("/api/v1/recommendations/domains/{domain}", q(limit=25), non_empty="items"),
    ),
    "/recommendations/detail": (
        *_SHELL,
        ApiCall(
            "/api/v1/recommendations/domains/{domain}",
            q(limit=25),
            capture=(("recommendation_id", ("items", 0, "recommendation_id")),),
            non_empty="items",
        ),
        ApiCall(
            "/api/v1/recommendations/domains/{domain}/items/{recommendation_id}",
            needs=("recommendation_id",),
            non_empty="recommendation",
        ),
    ),
    "/reconciliation": (
        *_SHELL,
        ApiCall("/api/v1/reconciliation/domains/{domain}", q(days=30)),
    ),
    "/replay/traces": (
        *_SHELL,
        ApiCall(
            "/api/v1/replay/domains/{domain}/traces",
            q(page_size=25),
            capture=(("trace_id", ("items", 0, "trace_id")),),
            non_empty="items",
        ),
        ApiCall(
            "/api/v1/replay/domains/{domain}/traces/{trace_id}",
            needs=("trace_id",),
            non_empty="spans",
        ),
    ),
    "/reports": (
        *_SHELL,
        ApiCall(_REPORTS, q(limit=25), non_empty="items", as_persona="analyst"),
    ),
    "/reports/view": (
        *_SHELL,
        ApiCall(
            _REPORTS,
            q(limit=25),
            capture=(("report_id", ("items", 0, "id")),),
            non_empty="items",
            as_persona="analyst",
        ),
        ApiCall(
            _REPORTS + "/{report_id}",
            needs=("report_id",),
            non_empty="id",
            as_persona="analyst",
        ),
    ),
    "/review": (*_SHELL, ApiCall(_REVIEW, q(limit=25), non_empty="items")),
    "/review/item": (
        *_SHELL,
        ApiCall(
            _REVIEW,
            q(limit=25),
            capture=(("item_id", ("items", 0, "item_id")),),
            non_empty="items",
        ),
        ApiCall(_REVIEW + "/{item_id}", needs=("item_id",), non_empty="item_id"),
    ),
    "/sandbox": (*_SHELL, ApiCall("/api/v1/sandbox/status")),
    # PRP-31: the missing UI surfaces. Mutations (decisions, deprecate, recertify, stale-agent
    # confirm, emergency disable) need a user action and are not listed. The edge page and the
    # stale-agents page issue no GET on render: the edge id arrives in the URL and the dry run is
    # a POST.
    "/admin/execution-control": (*_SHELL, _EMERGENCY),
    "/audit": (
        *_SHELL,
        ApiCall("/api/v1/audit/domains"),
        ApiCall("/api/v1/audit/domains/{domain}/records", q(page_size=50)),
    ),
    "/catalog": (
        *_SHELL,
        ApiCall("/api/v1/catalog/domains/{domain}/entities", q(page_size=50)),
    ),
    "/catalog/edge": _SHELL,
    "/catalog/entity": (
        *_SHELL,
        ApiCall(
            "/api/v1/catalog/domains/{domain}/entities",
            q(page_size=50),
            capture=(("entity_id", ("items", 0, "id")),),
        ),
        ApiCall("/api/v1/catalog/entities/{entity_id}", needs=("entity_id",)),
    ),
    "/catalog/recertifications": (
        *_SHELL,
        ApiCall("/api/v1/catalog/recertifications", q(within_days=30, page_size=50)),
    ),
    "/catalog/stale-agents": _SHELL,
    "/deploy": _SHELL,
    "/deploy/capabilities": (
        *_SHELL,
        ApiCall("/api/v1/capabilities", q(cloud="commercial")),
    ),
    "/evaluations": (
        *_SHELL,
        ApiCall("/api/v1/evaluation/domains/{domain}/results", q(limit=50)),
    ),
    "/federation": (*_SHELL, ApiCall("/api/v1/federation/summary", q(days=30))),
    "/finops/forecast": (
        *_SHELL,
        ApiCall(
            "/api/v1/finops/domains/{domain}/forecast",
            q(history_days=30, horizon_days=30, currency="USD"),
        ),
    ),
    "/workspaces/admin": _workspace("admin"),
    "/workspaces/analyst": _workspace("analyst"),
    "/workspaces/auditor": _workspace("auditor"),
    "/workspaces/steward": _workspace("steward"),
    "/workspaces/viewer": _workspace("viewer"),
}

#: The copilot dock is in the shell of every page but only calls the API when a user sends a
#: message (``POST /api/v1/copilot/conversations/...``); with ``NS_COPILOT_MODE=disabled`` (the
#: compose default) those answer 503 ``copilot_unconfigured``. Expected, and listed here.
COPILOT_ROUTES_503: Final = ("/api/v1/copilot/conversations",)

#: Not requested over plain HTTP by these suites.
NOT_COVERED_OVER_HTTP: Final[dict[str, str]] = {
    "/api/v1/realtime/ws": "WebSocket (map live deltas); covered by the realtime suites",
    "POST /api/v1/copilot/conversations": "a user action, not a render-time call",
}
