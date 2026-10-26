"""MCP server builder (PRP-29 item 8), following the mount contract of ``mcp/server/__init__.py``.

``mcp_server`` is OPTIONAL:

* ``NS_MCP_RESOURCE_SERVER_URL`` unset: ``disabled``. No ``/mcp`` route exists and the RFC 9728
  metadata route keeps answering 503 ``mcp_unconfigured``.
* Set: ``load_mcp_server_settings`` (invalid -> ``failed("mcp_settings_invalid")``), then an MCP
  ``JwtValidator`` from ``mcp_jwt_config`` (the deployment's cloud and ``NS_AUTH_TENANT_ID``, the
  MCP audiences ONLY, the Entra JWKS over ``httpx``), then, because the authz builder already ran
  ``configure_authz``, ``create_mcp_server(app, settings, validator=..., rest_audiences=
  NS_AUTH_AUDIENCES)``. The factory refuses MCP audiences that overlap the REST ones and a
  cloud/tenant binding that differs from REST authz (``failed("mcp_config_invalid")``). Finally
  the exact-path ``Route("/mcp")`` is appended to ``app.router.routes`` and the existing app
  lifespan runs the SDK session manager.

The route is appended only here, at composition time: ``create_app`` (and so the exported
``openapi.json``) never has it, and a Starlette ``Route`` is not an OpenAPI operation anyway.
MCP tools reach the PRP-17 action plane through ``app.state`` (``StatePorts.action_plane``),
i.e. the ONE ``ACTION_SERVICE`` the planes builder published; this builder requires it.

Test code may hand a prebuilt MCP ``JwtValidator`` through ``ctx.overrides.backend(
"mcp_validator")`` (it must still accept exactly the MCP audiences); ``main.create`` never does.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

import httpx
from neurosphere_core.auth.jwt import JwtValidator, create_jwt_validator
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.jwt.jwks import DEFAULT_FETCH_TIMEOUT_SECONDS
from neurosphere_core.errors import InvalidSchemaError

from neurosphere_api.mcp.server import (
    McpServerSettings,
    create_mcp_server,
    load_mcp_server_settings,
    mcp_jwt_config,
)
from neurosphere_api.runtime.builders import (
    ACTION_SERVICE,
    AUTH_SETTINGS,
    AUTHENTICATOR,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("mcp_server",)


class _HttpxCloser:
    """Adapts ``httpx.AsyncClient.aclose`` to the ``ClientLifetime`` ``close`` contract."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def close(self) -> None:
        await self._client.aclose()


def _validator(ctx: BuildContext, settings: McpServerSettings, tenant_id: str) -> JwtValidator:
    override = ctx.overrides.backend("mcp_validator")
    if override is not None:
        if not isinstance(override, JwtValidator):
            raise ComponentUnavailableError("mcp_validator_invalid")
        return override
    try:
        config = mcp_jwt_config(ctx.settings, settings, tenant_id=tenant_id)
    except InvalidSchemaError:
        raise ComponentUnavailableError("mcp_config_invalid") from None
    client = httpx.AsyncClient(timeout=DEFAULT_FETCH_TIMEOUT_SECONDS, follow_redirects=False)
    ctx.lifetime.register(_HttpxCloser(client))
    clock = ctx.overrides.clock
    if clock is None:
        return create_jwt_validator(config, client)
    return create_jwt_validator(config, client, clock=clock)


def _date_clock(ctx: BuildContext) -> Callable[[], datetime] | None:
    clock = ctx.overrides.clock
    if clock is None:
        return None
    return lambda: datetime.fromtimestamp(clock(), UTC)


def _mount(ctx: BuildContext, settings: McpServerSettings) -> None:
    # Mount contract step 3: only after configure_authz succeeded (AUTHENTICATOR is published
    # by the authz builder right after it).
    ctx.shared(AUTHENTICATOR)
    auth = ctx.shared(AUTH_SETTINGS)
    ctx.shared(ACTION_SERVICE)  # MCP tools share the ONE composed executor
    if auth.tenant_id is None:
        raise ComponentUnavailableError("tenant_id_missing")
    try:
        tenant_id = normalize_tenant_id(auth.tenant_id)
    except ValueError:
        raise ComponentUnavailableError("tenant_id_invalid") from None
    validator = _validator(ctx, settings, tenant_id)
    try:
        mount = create_mcp_server(
            ctx.app,
            settings,
            validator=validator,
            clock=_date_clock(ctx),
            rest_audiences=auth.audiences,
        )
    except InvalidSchemaError:
        raise ComponentUnavailableError("mcp_config_invalid") from None
    ctx.app.router.routes.append(mount.route())


def build(ctx: BuildContext) -> None:
    try:
        settings = load_mcp_server_settings()
    except InvalidSchemaError:
        ctx.failed("mcp_server", "mcp_settings_invalid")
        return
    if settings is None:
        ctx.disabled("mcp_server")
        return
    ctx.attempt("mcp_server", lambda: _mount(ctx, settings))


BUILDER: Final = BuilderSpec("mcp", COMPONENTS, build)
