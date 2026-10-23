"""Local-development stdio entry point for the MCP server (PRP-22 item 1, clarification 6).

stdio is never authenticated by the MCP spec, so the hosted server is streamable HTTP only. This
entry point exists for a developer's machine and REFUSES unless both hold:

* ``NS_ENV=local`` (the deployment settings), and
* the MCP token validator trusts the local dev issuer (``JwtConfig.dev_issuer``, itself only
  constructible when ``NS_ENV=local``).

It then requires a dev-issuer token for the MCP audience with the required scope, verified by the
same ``McpTokenVerifier``; the session runs as that principal and every tool call still derives
its scope from the policy store. An Entra token is refused here: production identities never
ride an unauthenticated transport.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.stdio import stdio_server
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError, UnauthorizedError

from neurosphere_api.mcp.server.factory import McpServerMount
from neurosphere_api.mcp.server.verifier import McpAccessToken

__all__ = ["StdioTransport", "check_stdio_allowed", "run_stdio_dev"]

StdioTransport = Callable[[], AbstractAsyncContextManager[tuple[Any, Any]]]


def check_stdio_allowed(settings: Settings, mount: McpServerMount) -> None:
    """Raise ``invalid_schema`` (reason ``stdio_refused``) unless local + dev issuer."""
    if settings.env != "local":
        raise InvalidSchemaError(
            "the stdio MCP entry point is available only when NS_ENV=local",
            reason="stdio_refused",
        )
    config = mount.validator.config
    if config.env != "local" or config.dev_issuer is None:
        raise InvalidSchemaError(
            "the stdio MCP entry point requires the local dev issuer", reason="stdio_refused"
        )


async def run_stdio_dev(
    mount: McpServerMount,
    settings: Settings,
    *,
    dev_token: str,
    transport: StdioTransport | None = None,
) -> None:
    """Serve ``mount.server`` over stdio as the dev-token principal (local development only)."""
    check_stdio_allowed(settings, mount)
    access = await mount.verifier.verify_token(dev_token)
    if not isinstance(access, McpAccessToken) or access.verified.issuer_kind != "dev":
        raise UnauthorizedError("a local dev-issuer token is required", reason="stdio_dev_token")
    if access.resource != mount.settings.resource_server_url:
        raise UnauthorizedError(
            "the dev token is not for the MCP resource", reason="stdio_dev_token"
        )
    if mount.settings.required_scope not in access.scopes:
        raise UnauthorizedError("the dev token lacks the required scope", reason="stdio_dev_token")
    open_transport: StdioTransport = transport or stdio_server
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        async with open_transport() as (read_stream, write_stream):
            await mount.server.run(
                read_stream, write_stream, mount.server.create_initialization_options()
            )
    finally:
        auth_context_var.reset(reset)
