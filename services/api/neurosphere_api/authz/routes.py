"""Public-route allowlist and route permission inventory (PRP-06 item 3).

Rule: every route either declares a permission through :func:`require` (anywhere in its
dependency tree, including router- or decorator-level ``dependencies=[...]``) or its exact path
is on the public allowlist. The allowlist is ``/healthz`` and ``/readyz`` plus the OpenAPI
schema and docs paths *only when the app has them configured* (non-``None`` on the app).

WebSocket routes follow a stricter rule. The HTTP ``require`` dependency reads a ``Request`` and
cannot authorize a handshake, so a permission marker alone proves nothing for a WebSocket. A
WebSocket route is compliant only when its exact path is in :data:`GATEWAY_AUTHENTICATED_WEBSOCKETS`
(a reasoned entry naming the code that authenticates and authorizes the connection itself) AND it
declares that entry's permission marker. The HTTP public, producer and self-authenticated
allowlists never apply to a WebSocket route.

:func:`undeclared_routes` lists violations; ``compose_app`` calls
:func:`verify_route_permissions` after every builder ran, so an undeclared route fails app boot.
Public routes get no blanket allow; they simply do not call ``require``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIWebSocketRoute, RouteContext, iter_route_contexts
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import InvalidSchemaError
from starlette.routing import BaseRoute, Mount, WebSocketRoute

from neurosphere_api.authz.dependencies import PERMISSION_MARKER
from neurosphere_api.authz.state import STATE_ATTRIBUTE, AuthzState

__all__ = [
    "GATEWAY_AUTHENTICATED_WEBSOCKETS",
    "MCP_METADATA_PATH",
    "MCP_MOUNT_STATE_ATTRIBUTE",
    "PRODUCER_AUTHENTICATED_PATHS",
    "PUBLIC_PATHS",
    "SELF_AUTHENTICATED_PATHS",
    "RouteEntry",
    "WebSocketGuard",
    "public_paths_for",
    "route_inventory",
    "undeclared_routes",
    "verify_route_permissions",
]

#: RFC 9728 protected-resource metadata of the MCP server (PRP-22 item 1): public by definition
#: (clients read it before they hold a token). Equals ``neurosphere_api.mcp.server``'s
#: ``PROTECTED_RESOURCE_METADATA_PATH`` (a test pins that); not imported to keep authz leaf-level.
MCP_METADATA_PATH: Final = "/.well-known/oauth-protected-resource/mcp"

#: Always-public probe paths (PRP-05 health router) and the MCP RFC 9728 metadata path.
PUBLIC_PATHS: Final = frozenset({"/healthz", "/readyz", MCP_METADATA_PATH})

#: Exact paths served by a mounted sub-application that authenticates every request itself
#: (the MCP streamable HTTP endpoint validates the bearer token, audience, resource and scope
#: and answers 401/403 with ``WWW-Authenticate``). Not public and not ``require``d: a separate
#: category like :data:`PRODUCER_AUTHENTICATED_PATHS`, exact-path only, a plain route (never a
#: ``Mount``). Equals ``neurosphere_api.mcp.server``'s ``MCP_PATH`` (a test pins that).
SELF_AUTHENTICATED_PATHS: Final = frozenset({"/mcp"})

#: ``app.state`` attribute under which ``create_mcp_server`` stores its ``McpServerMount`` (a test
#: pins it to the server package's ``STATE_ATTRIBUTE``). The exemption above only applies to the
#: route whose endpoint is that mount's ``asgi_app``.
MCP_MOUNT_STATE_ATTRIBUTE: Final = "mcp_server"

#: Ingest-edge paths whose *producers* authenticate by registered credential inside the ingest
#: service (``Authorization: Bearer <producer_id>.<secret>``). Not public and not ``require``d:
#: a separate category, exact-path and ``POST``-only. ``tests/ingest`` asserts this set equals
#: the ingest router's POST paths and that each returns 401 without a credential. Both forms are
#: listed: ``/api/v1/ingest/...`` and the deprecated ``/v1/ingest/...`` alias (PRP-29 item 4),
#: which serves the same router for one release.
PRODUCER_AUTHENTICATED_PATHS: Final = frozenset(
    {
        "/api/v1/ingest/otlp/traces",
        "/api/v1/ingest/otlp/metrics",
        "/api/v1/ingest/events",
        "/v1/ingest/otlp/traces",
        "/v1/ingest/otlp/metrics",
        "/v1/ingest/events",
    }
)

_WEBSOCKET: Final = ("WEBSOCKET",)


@dataclass(frozen=True, slots=True)
class WebSocketGuard:
    """Why a WebSocket route is safe: the permission it enforces and where it enforces it."""

    permission: Permission
    reason: str


#: Exact WebSocket paths whose handler authenticates the handshake and authorizes every message
#: itself, with the permission the route must also declare by marker. No public WebSockets.
GATEWAY_AUTHENTICATED_WEBSOCKETS: Final[Mapping[str, WebSocketGuard]] = MappingProxyType(
    {
        # PRP-18 item 1: ``realtime.gateway.serve`` validates the bearer token (header or
        # ``ns.bearer`` subprotocol) with the installed authenticator and derives the scope before
        # serving anything (4401 / 4403 / 1013 on failure, closed when authz is unconfigured),
        # then checks ``data.read`` on the target domain for every subscribe and every delta.
        "/api/v1/realtime/ws": WebSocketGuard(
            Permission.DATA_READ,
            "realtime gateway authenticates the handshake and checks data.read per domain",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class RouteEntry:
    path: str
    methods: tuple[str, ...]
    permissions: tuple[str, ...]
    public: bool
    producer_authenticated: bool = False
    self_authenticated: bool = False
    gateway_authenticated: bool = False

    @property
    def websocket(self) -> bool:
        return self.methods == _WEBSOCKET

    @property
    def compliant(self) -> bool:
        if self.websocket:
            # A marker cannot authorize a handshake; only a reasoned gateway entry can.
            return self.gateway_authenticated
        return (
            self.public
            or bool(self.permissions)
            or self.producer_authenticated
            or self.self_authenticated
        )


def public_paths_for(app: FastAPI, *, extra: Iterable[str] = ()) -> frozenset[str]:
    """Allowlist for ``app``: probes, configured OpenAPI/docs paths and explicit extras."""
    paths = set(PUBLIC_PATHS)
    if app.openapi_url:
        paths.add(app.openapi_url)
        if app.docs_url:
            paths.add(app.docs_url)
            if app.swagger_ui_oauth2_redirect_url:
                paths.add(app.swagger_ui_oauth2_redirect_url)
        if app.redoc_url:
            paths.add(app.redoc_url)
    for path in extra:
        if not path.startswith("/") or any(c in path for c in "{}*"):
            raise InvalidSchemaError(
                "public paths must be exact, absolute and parameter-free", reason="config"
            )
        paths.add(path)
    return frozenset(paths)


def _installed_allowlist(app: FastAPI) -> frozenset[str]:
    state = getattr(app.state, STATE_ATTRIBUTE, None)
    return state.public_paths if isinstance(state, AuthzState) else public_paths_for(app)


def _permissions(dependant: Dependant) -> Iterator[str]:
    marker = getattr(dependant.call, PERMISSION_MARKER, None)
    if isinstance(marker, Permission):
        yield marker.value
    for child in dependant.dependencies:
        yield from _permissions(child)


def _mounted_mcp_endpoint(app: FastAPI) -> object | None:
    """The ASGI app of the MCP server mount ``create_mcp_server`` stored on ``app.state``.

    Read by attribute name (authz stays leaf-level); ``None`` when no MCP server is mounted, in
    which case no route can inherit the self-authenticated exemption.
    """
    mount = getattr(app.state, MCP_MOUNT_STATE_ATTRIBUTE, None)
    return getattr(mount, "asgi_app", None)


def _is_mcp_endpoint(original: BaseRoute, source: Any, endpoint: object | None) -> bool:
    """True when the route's endpoint *is* the mounted MCP server app (identity, not a path)."""
    if endpoint is None:
        return False
    return any(getattr(r, "endpoint", None) is endpoint for r in (original, source))


def _entry(
    context: RouteContext, allow: frozenset[str], mcp_endpoint: object | None = None
) -> RouteEntry:
    original = context.original_route
    # FastAPI >= 0.143 keeps included routers unflattened. For included API routes the context
    # itself is the effective route; for other included routes (websocket, plain Starlette,
    # Mount) the effective, prefixed route is ``starlette_route``. Either carries the
    # include-time and router-level dependencies; the route's own dependant is the fallback
    # (which can only under-report permissions, i.e. flag a route, never hide one).
    effective = getattr(context, "starlette_route", None)
    source: Any = effective if isinstance(effective, BaseRoute) else context
    path = getattr(source, "path", None)
    path = path if isinstance(path, str) and path else repr(original)
    dependant = getattr(source, "dependant", None)
    if not isinstance(dependant, Dependant):
        dependant = getattr(original, "dependant", None)
    perms = tuple(sorted(set(_permissions(dependant)))) if isinstance(dependant, Dependant) else ()
    websocket = isinstance(original, APIWebSocketRoute | WebSocketRoute)
    if websocket:
        methods: tuple[str, ...] = _WEBSOCKET
    else:
        methods = tuple(sorted(getattr(source, "methods", None) or ()))
    # A mounted sub-application is opaque to this check, so it is never public by default.
    # The HTTP allowlists never cover a WebSocket route.
    http = not isinstance(original, Mount) and not websocket
    public = http and path in allow
    producer = http and path in PRODUCER_AUTHENTICATED_PATHS and methods == ("POST",)
    # Exact path AND the route is the MCP server mount's own endpoint: a different route that
    # merely sits at /mcp does not inherit the exemption.
    self_authenticated = (
        http
        and path in SELF_AUTHENTICATED_PATHS
        and _is_mcp_endpoint(original, source, mcp_endpoint)
    )
    guard = GATEWAY_AUTHENTICATED_WEBSOCKETS.get(path) if websocket else None
    gateway = guard is not None and guard.permission.value in perms
    return RouteEntry(
        path=path,
        methods=methods,
        permissions=perms,
        public=public,
        producer_authenticated=producer,
        self_authenticated=self_authenticated,
        gateway_authenticated=gateway,
    )


def route_inventory(
    app: FastAPI, *, public_paths: frozenset[str] | None = None
) -> tuple[RouteEntry, ...]:
    """Every route of ``app`` with its declared permissions and allowlist status.

    Routes are enumerated with ``fastapi.routing.iter_route_contexts`` (the iterator FastAPI's
    own OpenAPI generation uses), so routes inside included routers are seen at their full path.
    The allowlist defaults to the one ``configure_authz`` installed, else :func:`public_paths_for`.
    """
    allow = public_paths if public_paths is not None else _installed_allowlist(app)
    endpoint = _mounted_mcp_endpoint(app)
    return tuple(_entry(context, allow, endpoint) for context in iter_route_contexts(app.routes))


def undeclared_routes(
    app: FastAPI, *, public_paths: frozenset[str] | None = None
) -> tuple[RouteEntry, ...]:
    """Routes that neither declare a permission nor sit on an allowlist (see module docstring)."""
    return tuple(e for e in route_inventory(app, public_paths=public_paths) if not e.compliant)


def verify_route_permissions(app: FastAPI, *, public_paths: frozenset[str] | None = None) -> None:
    """Startup guard: raise ``invalid_schema`` (reason ``route_without_permission``)."""
    missing = undeclared_routes(app, public_paths=public_paths)
    if missing:
        raise InvalidSchemaError(
            "routes without a declared permission: "
            + ", ".join(f"{','.join(e.methods)} {e.path}" for e in missing),
            reason="route_without_permission",
        )
