"""Scoped MCP server: OAuth 2.1 resource server over the PRP-19 tools and PRP-17 actions.

PRP-22 item 1. Python ``mcp`` 2.3, spec 2026-07-28, streamable HTTP only (a local stdio entry
point exists for ``NS_ENV=local`` with the dev issuer and refuses otherwise).

Mount contract (wired by PRP-22 item 3; this package does not edit ``routers.py`` or ``app.py``):

1. Settings: ``settings = load_mcp_server_settings()`` (``NS_MCP_*``; ``None`` = MCP disabled).
2. Validator: ``validator = create_jwt_validator(mcp_jwt_config(ns_settings, settings,
   tenant_id=..., dev_issuer=...), http_client)``. Its audiences are the MCP audiences ONLY.
3. After ``configure_authz(app, ...)``: ``mount = create_mcp_server(app, settings,
   validator=validator)``. This stores the mount on ``app.state.mcp_server`` and checks that the
   MCP audiences are distinct from the REST audiences and that cloud/tenant bindings agree.
4. Route: ``app.router.routes.append(mount.route())`` - exact path :data:`MCP_PATH` (``/mcp``),
   every method, served by the SDK app (it authenticates itself: 401/403 with
   ``WWW-Authenticate``). It has no ``require`` dependency, so the route inventory must treat
   ``/mcp`` like the producer-authenticated ingest paths (self-authenticating, not public).
5. Metadata: ``register(registry)`` (this module) adds ``GET``
   :data:`PROTECTED_RESOURCE_METADATA_PATH` (``/.well-known/oauth-protected-resource/mcp``); it
   is public (add it to the public paths) and 503 ``mcp_unconfigured`` until step 3 ran.
6. Lifespan: ``async with mount.session_manager.run(): yield`` in the API lifespan (the SDK
   refuses requests until the session manager runs; ``run()`` may be entered once).

``app.state`` keys read at call time: ``authz`` (``AuthzState``: the REST ``ScopeSource`` and
timeout), ``catalog_repository``, ``aggregate_reader``, ``recommendation_store`` and the PRP-17
action-plane keys (``action_service``, ``intent_store``, ``hitl_service``, ``review_policies``,
``write_targets``, ``permission_rechecker``, ``execution_control``, ``audit_repository``,
optional ``action_api_settings`` / ``action_clock`` / ``reviewer_directory``). Written:
``mcp_server`` (``McpServerMount``). Anything unbound fails closed (401/503), never an allow.

No token passthrough: the inbound bearer is validated in-process and dropped; tools call core
services in-process with the caller's re-derived ``IdentityScope``. No module here opens an
outbound client (asserted statically and at runtime by the tests).
"""

from neurosphere_api.mcp.server.factory import (
    RESOURCE_URIS,
    SERVER_NAME,
    STATE_ATTRIBUTE,
    McpServerMount,
    create_mcp_server,
)
from neurosphere_api.mcp.server.router import PREFIX, build_router, get_mcp_mount, register
from neurosphere_api.mcp.server.settings import (
    DEFAULT_REQUIRED_SCOPE,
    ENV_PREFIX,
    MCP_PATH,
    PROTECTED_RESOURCE_METADATA_PATH,
    McpServerSettings,
    authorization_server_for,
    load_mcp_server_settings,
    mcp_jwt_config,
)
from neurosphere_api.mcp.server.stdio import check_stdio_allowed, run_stdio_dev
from neurosphere_api.mcp.server.tools import (
    ACTION_TOOL_NAMES,
    MCP_TOOL_NAMES,
    READ_TOOL_NAMES,
)
from neurosphere_api.mcp.server.verifier import (
    REDACTED_TOKEN,
    McpAccessToken,
    McpTokenVerifier,
)

__all__ = [
    "ACTION_TOOL_NAMES",
    "DEFAULT_REQUIRED_SCOPE",
    "ENV_PREFIX",
    "MCP_PATH",
    "MCP_TOOL_NAMES",
    "PREFIX",
    "PROTECTED_RESOURCE_METADATA_PATH",
    "READ_TOOL_NAMES",
    "REDACTED_TOKEN",
    "RESOURCE_URIS",
    "SERVER_NAME",
    "STATE_ATTRIBUTE",
    "McpAccessToken",
    "McpServerMount",
    "McpServerSettings",
    "McpTokenVerifier",
    "authorization_server_for",
    "build_router",
    "check_stdio_allowed",
    "create_mcp_server",
    "get_mcp_mount",
    "load_mcp_server_settings",
    "mcp_jwt_config",
    "register",
    "run_stdio_dev",
]
