"""RFC 9728 OAuth 2.0 Protected Resource Metadata for the MCP resource (PRP-22 item 1).

``GET /.well-known/oauth-protected-resource/mcp`` (RFC 9728 section 3.1: the well-known segment
sits between the host and the resource path ``/mcp``) returns the metadata of the mounted MCP
server: ``resource`` (the MCP resource identifier), ``authorization_servers`` (the Entra v2
issuer of the active cloud profile and tenant), ``scopes_supported`` and
``bearer_methods_supported: ["header"]``. It is public by definition (clients read it before
they hold a token) and carries no secret. ``OPTIONS`` on the same path answers a CORS preflight
(204, ``Access-Control-Allow-Origin: *``, methods ``GET, OPTIONS``), mirroring the SDK. Until
``create_mcp_server`` has stored the mount on ``app.state.mcp_server`` both fail closed with 503
(reason ``mcp_unconfigured``).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from neurosphere_core.errors import DependencyTransientError

from neurosphere_api.mcp.server.factory import STATE_ATTRIBUTE, McpServerMount
from neurosphere_api.mcp.server.settings import PROTECTED_RESOURCE_METADATA_PATH
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "get_mcp_mount", "register"]

PREFIX: Final = PROTECTED_RESOURCE_METADATA_PATH
_CACHE_CONTROL: Final = "public, max-age=3600"
#: CORS preflight answer, the same policy the SDK's own RFC 9728 route applies: any origin,
#: GET/OPTIONS only, and only the ``MCP-Protocol-Version`` request header beyond the safelisted
#: ones. No credentials are allowed (the document is public).
_PREFLIGHT_HEADERS: Final = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, OPTIONS"),
    ("Access-Control-Allow-Headers", "MCP-Protocol-Version"),
    ("Access-Control-Max-Age", "600"),
)


def get_mcp_mount(request: Request) -> McpServerMount:
    mount = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(mount, McpServerMount):
        raise DependencyTransientError("MCP server is not configured", reason="mcp_unconfigured")
    return mount


def build_router() -> APIRouter:
    router = APIRouter(tags=["mcp"])

    @router.get("", include_in_schema=False)
    async def protected_resource_metadata(request: Request) -> JSONResponse:
        mount = get_mcp_mount(request)
        return JSONResponse(
            mount.metadata.model_dump(mode="json", exclude_none=True),
            headers={"Cache-Control": _CACHE_CONTROL, "Access-Control-Allow-Origin": "*"},
        )

    @router.options("", include_in_schema=False)
    async def protected_resource_metadata_preflight(request: Request) -> Response:
        get_mcp_mount(request)
        return Response(status_code=204, headers=dict(_PREFLIGHT_HEADERS))

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
