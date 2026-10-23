"""Build the MCP server: SDK resource-server auth, scoped handlers, streamable HTTP app.

:func:`create_mcp_server` returns an :class:`McpServerMount`. The server is the SDK low-level
``Server`` (``mcp`` 2.3, spec 2026-07-28) behind the SDK's OAuth 2.1 resource-server stack:

* ``AuthSettings(..., validate_token_resource=True)`` is written out explicitly (the SDK leaves it
  unset by default); a test fails if the keyword is absent or not ``True``.
* Token validation is :class:`~neurosphere_api.mcp.server.verifier.McpTokenVerifier` over a
  PRP-06 ``JwtValidator`` whose audiences are exactly the MCP audiences. Construction fails if
  they differ, or overlap the REST API audiences, or the cloud/tenant binding disagrees with the
  REST authorization state.
* Missing, invalid, expired, wrong-audience or wrong-resource token: 401 with
  ``WWW-Authenticate: Bearer ... resource_metadata="<RFC 9728 URL>"``. Valid token without the
  required scope: 403 ``insufficient_scope``. Both answered by the SDK middleware.
* Every ``tools/call`` and ``resources/read`` re-derives ``IdentityScope`` from the verified
  claims through the SAME ``ScopeSource`` as REST (``app.state.authz``): revocation (within the
  revocation TTL) and policy-store outages fail closed as tool errors (403 / 503), never an
  empty allow.

Transport is streamable HTTP only (JSON responses, stateless), with the SDK's Host/Origin guard
pinned to the resource host. See ``neurosphere_api.mcp.server`` for the mount contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import mcp_types as types
from fastapi import FastAPI, HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import ProtectedResourceMetadata
from mcp.shared.exceptions import MCPError
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.scope import (
    Permission,
    ScopeDerivation,
    ScopeDeriver,
    domains_with_permission,
)
from neurosphere_core.copilot.tools import (
    ArgumentNotAllowedError,
    RefusalSink,
    ScopeArgumentRefusedError,
    ToolNotRegisteredError,
    ToolRegistry,
    ToolResult,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    UnauthorizedError,
)
from neurosphere_core.scope import IdentityScope
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.authz.state import STATE_ATTRIBUTE as AUTHZ_STATE_ATTRIBUTE
from neurosphere_api.authz.state import AuthzState
from neurosphere_api.mcp.server.settings import (
    MCP_PATH,
    McpServerSettings,
    authorization_server_for,
)
from neurosphere_api.mcp.server.tools import (
    ANNOTATIONS,
    IntentNotVisibleError,
    StatePorts,
    build_mcp_registry,
)
from neurosphere_api.mcp.server.verifier import McpAccessToken, McpTokenVerifier
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "RESOURCE_URIS",
    "SERVER_NAME",
    "STATE_ATTRIBUTE",
    "McpServerMount",
    "create_mcp_server",
]

_LOG = logging.getLogger("neurosphere_api.mcp.server")

#: ``app.state`` key the factory sets (the RFC 9728 metadata route reads it).
STATE_ATTRIBUTE: Final = "mcp_server"
SERVER_NAME: Final = "neurosphere"
SERVER_VERSION: Final = "0.1.0"

ABOUT_URI: Final = "neurosphere://mcp/about"
SCOPE_URI: Final = "neurosphere://scope/current"
RECOMMENDATIONS_URI: Final = "neurosphere://recommendations/recent"
RESOURCE_URIS: Final = (ABOUT_URI, RECOMMENDATIONS_URI, SCOPE_URI)

_INSTRUCTIONS: Final = (
    "NeuroSphere MCP server. Read tools return catalog entities, ingested cost, latency and "
    "error aggregates, and recommendations from the caller's authorized domains only. Action "
    "tools draft, validate and present confirmation for action intents; they never confirm, "
    "execute or approve. A human confirms in the NeuroSphere UI or REST API. Scope, domain and "
    "customer arguments are refused: authorization comes from the caller's token and the "
    "NeuroSphere policy store. This server returns only data NeuroSphere already holds; it does "
    "not discover agents on the caller's machine or network and does not provide complete "
    "telemetry."
)
_RECENT_RECOMMENDATIONS_QUERY: Final = {
    "query": {
        "schema_version": "1.0.0",
        "operation": "list",
        "entity": "recommendation",
        "budget": {"timeout_ms": 5000, "limit": 20, "max_depth": 0},
    }
}
_INTERNAL: Final = {
    "code": "internal",
    "reason": "mcp_tool_failed",
    "status": 500,
    "retryable": False,
    "detail": "the tool failed",
}
_NOT_FOUND: Final = {
    "code": "not_found",
    "reason": "intent_not_found",
    "status": 404,
    "retryable": False,
    "detail": "not found",
}
_REFUSALS: Final = (ScopeArgumentRefusedError, ArgumentNotAllowedError, ToolNotRegisteredError)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class McpServerMount:
    """Everything the API needs to serve MCP. See the package docstring for the contract."""

    settings: McpServerSettings
    auth_settings: AuthSettings
    verifier: McpTokenVerifier
    validator: JwtValidator
    server: Server[Any]
    asgi_app: Starlette
    session_manager: StreamableHTTPSessionManager
    metadata: ProtectedResourceMetadata

    def route(self) -> Route:
        """Exact-path route (all methods) to append to the API app's routes."""
        return Route(MCP_PATH, endpoint=self.asgi_app)


# -- configuration checks ------------------------------------------------------------------------


def _config_error(detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason="config")


def _check_validator(validator: JwtValidator, settings: McpServerSettings) -> None:
    if not isinstance(validator, JwtValidator):
        raise _config_error("the MCP token validator must be a JwtValidator")
    if set(validator.config.audiences) != set(settings.effective_audiences):
        raise _config_error("the MCP token validator must accept exactly the MCP audiences")


def _rest_overlap(authz: object, mcp_audiences: set[str], rest_audiences: set[str]) -> bool:
    rest = set(rest_audiences)
    if isinstance(authz, AuthzState) and isinstance(authz.authenticator, JwtValidator):
        rest |= set(authz.authenticator.config.audiences)
    return bool(rest & mcp_audiences)


def _check_binding(authz: object, validator: JwtValidator) -> None:
    if not isinstance(authz, AuthzState):
        return
    cfg = validator.config
    for bound in (authz.authenticator, authz.scope_source):
        if isinstance(bound, JwtValidator | ScopeDeriver) and (
            bound.config.cloud is not cfg.cloud or bound.config.tenant_id != cfg.tenant_id
        ):
            raise _config_error("MCP and REST authorization are bound to different clouds/tenants")


# -- handlers ------------------------------------------------------------------------------------


def _error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, NeuroSphereError):
        payload: dict[str, Any] = {
            "code": exc.code,
            "reason": exc.reason,
            "status": exc.status,
            "retryable": exc.retryable,
            "detail": exc.detail or exc.title,
        }
        if exc.errors:
            payload["errors"] = [{"pointer": i.pointer, "detail": i.detail} for i in exc.errors]
        return payload
    if isinstance(exc, IntentNotVisibleError) or (
        isinstance(exc, HTTPException) and exc.status_code == 404
    ):
        return dict(_NOT_FOUND)
    return dict(_INTERNAL)


def _json(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _tool_result(result: ToolResult) -> types.CallToolResult:
    payload = result.model_dump(mode="json")
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=_json(payload))],
        structured_content=payload,
        is_error=False,
    )


def _tool_error(exc: BaseException) -> types.CallToolResult:
    payload = {"error": _error_payload(exc)}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=_json(payload))],
        structured_content=payload,
        is_error=True,
    )


class _Handlers:
    def __init__(
        self,
        app: FastAPI,
        settings: McpServerSettings,
        *,
        clock: Clock,
        sink: RefusalSink | None,
        rest_audiences: set[str],
    ) -> None:
        self._app = app
        self._settings = settings
        self._clock = clock
        self._sink = sink
        self._rest_audiences = rest_audiences
        self._ports = StatePorts(app)
        manifest = build_mcp_registry(self._ports, correlation_id="manifest", clock=clock)
        self._tools = [
            types.Tool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.args_model.model_json_schema(),
                annotations=types.ToolAnnotations(
                    read_only_hint=ANNOTATIONS[spec.name].read_only,
                    destructive_hint=False,
                    idempotent_hint=ANNOTATIONS[spec.name].idempotent,
                    open_world_hint=False,
                ),
            )
            for spec in manifest.manifest()
        ]

    # -- identity and scope ----------------------------------------------------------------

    async def _scope(self) -> IdentityScope:
        """Re-derive the caller's scope for this call: verified claims + the REST ScopeSource."""
        access = get_access_token()
        if not isinstance(access, McpAccessToken):
            raise UnauthorizedError("bearer token required", reason="missing_token")
        authz = getattr(self._app.state, AUTHZ_STATE_ATTRIBUTE, None)
        if not isinstance(authz, AuthzState):
            raise DependencyTransientError(
                "authorization is not configured", reason="authz_unconfigured"
            )
        if _rest_overlap(authz, set(self._settings.effective_audiences), self._rest_audiences):
            raise DependencyTransientError(
                "MCP audiences overlap the REST API audiences", reason="mcp_audience_overlap"
            )
        try:
            async with asyncio.timeout(authz.timeout_seconds):
                derivation = await authz.scope_source.derive(access.verified)
        except (UnauthorizedError, ForbiddenError, DependencyTransientError):
            raise
        except TimeoutError as exc:
            raise DependencyTransientError(
                "authorization timed out", reason="authz_timeout"
            ) from exc
        except Exception as exc:
            raise DependencyTransientError(
                "authorization unavailable", reason="authz_unavailable"
            ) from exc
        if not isinstance(derivation, ScopeDerivation) or not isinstance(
            derivation.scope, IdentityScope
        ):
            raise DependencyTransientError(
                "scope source returned an invalid scope", reason="authz_invalid_scope"
            )
        return derivation.scope

    def _registry(self, ctx: ServerRequestContext[Any, Any]) -> ToolRegistry:
        request = ctx.request
        raw = correlation_id_of(request.scope) if isinstance(request, Request) else None
        correlation = audit_correlation_id(raw or str(uuid.uuid4()))
        return build_mcp_registry(
            self._ports, correlation_id=correlation, clock=self._clock, sink=self._sink
        )

    # -- tools -----------------------------------------------------------------------------

    async def list_tools(
        self, ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=list(self._tools))

    async def call_tool(
        self, ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        name = params.name
        try:
            scope = await self._scope()
            result = await self._registry(ctx).invoke(name, dict(params.arguments or {}), scope)
        except _REFUSALS as exc:
            _LOG.warning(
                "mcp tool call refused",
                extra={
                    "tool": name if name in ANNOTATIONS else "<unregistered>",
                    "reason": exc.reason,
                },
            )
            return _tool_error(exc)
        except (NeuroSphereError, IntentNotVisibleError, HTTPException) as exc:
            _LOG.info(
                "mcp tool call denied or failed",
                extra={"tool": name if name in ANNOTATIONS else "<unregistered>"},
            )
            return _tool_error(exc)
        except Exception as exc:
            _LOG.exception("mcp tool raised an unexpected exception")
            return _tool_error(exc)
        return _tool_result(result)

    # -- resources -------------------------------------------------------------------------

    async def list_resources(
        self, ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    name="about",
                    uri=ABOUT_URI,
                    description="What this MCP server exposes and what it does not.",
                    mime_type="text/markdown",
                ),
                types.Resource(
                    name="current-scope",
                    uri=SCOPE_URI,
                    description="The caller's server-derived scope (domains and permissions).",
                    mime_type="application/json",
                ),
                types.Resource(
                    name="recent-recommendations",
                    uri=RECOMMENDATIONS_URI,
                    description="Recent recommendations in the caller's readable domains.",
                    mime_type="application/json",
                ),
            ]
        )

    async def read_resource(
        self, ctx: ServerRequestContext[Any, Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        if uri == ABOUT_URI:
            return self._contents(uri, _INSTRUCTIONS, "text/markdown")
        if uri not in RESOURCE_URIS:
            raise MCPError(code=types.INVALID_PARAMS, message="unknown resource", data={"uri": uri})
        try:
            scope = await self._scope()
            if uri == SCOPE_URI:
                text = _json(self._scope_summary(scope))
            else:
                result = await self._registry(ctx).invoke(
                    "list_recommendations", _RECENT_RECOMMENDATIONS_QUERY, scope
                )
                text = _json(result.model_dump(mode="json"))
        except NeuroSphereError as exc:
            raise MCPError(
                code=types.INTERNAL_ERROR,
                message="resource denied or unavailable",
                data=_error_payload(exc),
            ) from None
        except Exception:
            _LOG.exception("mcp resource raised an unexpected exception")
            raise MCPError(
                code=types.INTERNAL_ERROR, message="resource failed", data=dict(_INTERNAL)
            ) from None
        return self._contents(uri, text, "application/json")

    def _scope_summary(self, scope: IdentityScope) -> dict[str, Any]:
        now = self._clock()
        contract = scope.to_contract().model_dump(mode="json")
        return {
            "customer_id": scope.customer_id,
            "principal_pseudonym": contract["principal"]["principal_pseudonym"],
            "readable_domains": sorted(
                domains_with_permission(scope, Permission.DATA_READ, now=now)
            ),
            "proposable_domains": sorted(
                domains_with_permission(scope, Permission.ACTION_PROPOSE, now=now)
            ),
            "policy_version": scope.policy_version,
            "scope_hash": scope.scope_hash,
            "expires_at": contract["expires_at"],
        }

    @staticmethod
    def _contents(uri: str, text: str, mime_type: str) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=uri, text=text, mime_type=mime_type)]
        )


# -- factory -------------------------------------------------------------------------------------


def create_mcp_server(
    app: FastAPI,
    settings: McpServerSettings,
    *,
    validator: JwtValidator,
    clock: Clock | None = None,
    refusal_sink: RefusalSink | None = None,
    rest_audiences: Iterable[str] = (),
) -> McpServerMount:
    """Build the MCP server for ``app`` and store the mount on ``app.state.mcp_server``.

    ``validator`` is the MCP ``JwtValidator`` (``mcp_jwt_config`` + ``create_jwt_validator``).
    ``rest_audiences`` adds REST API audiences to the separation check beyond those of the
    installed ``app.state.authz`` validator. Any misconfiguration raises ``invalid_schema``.
    """
    _check_validator(validator, settings)
    rest = set(rest_audiences)
    authz = getattr(app.state, AUTHZ_STATE_ATTRIBUTE, None)
    mcp_audiences = set(settings.effective_audiences)
    if _rest_overlap(authz, mcp_audiences, rest) or settings.resource_server_url in rest:
        raise _config_error("MCP audiences must be distinct from the REST API audiences")
    _check_binding(authz, validator)

    issuer = authorization_server_for(validator.config)
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(settings.resource_server_url),
        required_scopes=[settings.required_scope],
        validate_token_resource=True,
    )
    verifier = McpTokenVerifier(
        validator,
        resource_server_url=settings.resource_server_url,
        resource_audiences=settings.effective_audiences,
    )
    handlers = _Handlers(
        app, settings, clock=clock or _utc_now, sink=refusal_sink, rest_audiences=rest
    )
    server: Server[Any] = Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        title="NeuroSphere",
        instructions=_INSTRUCTIONS,
        on_list_tools=handlers.list_tools,
        on_call_tool=handlers.call_tool,
        on_list_resources=handlers.list_resources,
        on_read_resource=handlers.read_resource,
    )
    hosts = [settings.resource_host, *settings.allowed_hosts]
    asgi_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[f"https://{host}" for host in hosts],
        ),
        auth=auth_settings,
        token_verifier=verifier,
    )
    metadata = ProtectedResourceMetadata(
        resource=AnyHttpUrl(settings.resource_server_url),
        authorization_servers=[AnyHttpUrl(issuer)],
        scopes_supported=[settings.required_scope],
        resource_name="NeuroSphere MCP",
    )
    mount = McpServerMount(
        settings=settings,
        auth_settings=auth_settings,
        verifier=verifier,
        validator=validator,
        server=server,
        asgi_app=asgi_app,
        session_manager=server.session_manager,
        metadata=metadata,
    )
    setattr(app.state, STATE_ATTRIBUTE, mount)
    return mount
