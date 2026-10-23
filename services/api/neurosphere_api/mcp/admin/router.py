"""MCP registration-admin routes, mounted at ``/api/v1/mcp/admin`` (PRP-22 item 3).

| Method | Path                                         | Permission      |
|--------|----------------------------------------------|-----------------|
| POST   | ``/servers``                                 | ``config.manage`` |
| GET    | ``/servers``                                 | ``config.manage`` |
| GET    | ``/servers/{server_id}``                     | ``config.manage`` |
| PATCH  | ``/servers/{server_id}`` (``If-Match``)      | ``config.manage`` |
| POST   | ``/servers/{server_id}/sync``                | ``config.manage`` |
| GET    | ``/servers/{server_id}/tools``               | ``config.manage`` |
| POST   | ``/servers/{server_id}/tools/{tool}/approval`` (``If-Match``) | ``config.manage`` |
| DELETE | ``/servers/{server_id}/tools/{tool}/approval`` (``If-Match``) | ``config.manage`` |

Every route requires ``config.manage`` on the server side (held in any domain; the same precedent
as the action kill switch and the discovery scan); hiding the navigation item is cosmetic. A new
or changed tool stays disabled until an administrator approves the exact hash they reviewed.
Until :func:`configure_mcp_admin` ran, routes fail closed with 503.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response, status
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.mcp.admin.models import (
    ApproveToolBody,
    RegisterServerBody,
    ServerPage,
    ServerView,
    SyncView,
    ToolList,
    UpdateServerBody,
    server_view,
    sync_view,
    tool_list,
)
from neurosphere_api.mcp.admin.service import McpAdminPlane, McpAdminService
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "STATE_ATTRIBUTE", "build_router", "configure_mcp_admin", "register"]

PREFIX: Final = "/api/v1/mcp/admin"
STATE_ATTRIBUTE: Final = "mcp_admin"
DEFAULT_REVOKE_REASON: Final = "revoked_by_administrator"

ConfigScope = Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))]
ServerPath = Annotated[str, Path(pattern=r"^mcp-[0-9a-f]{32}$")]
ToolPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,128}$")]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
OptionalIfMatch = Annotated[str | None, Header(alias="If-Match", min_length=1, max_length=300)]


def configure_mcp_admin(app: FastAPI, plane: McpAdminPlane) -> None:
    """Install the admin plane on ``app.state``."""
    setattr(app.state, STATE_ATTRIBUTE, plane)


def _service(request: Request) -> McpAdminService:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, McpAdminPlane):
        raise DependencyTransientError(
            "MCP administration is not configured", reason="mcp_admin_unconfigured"
        )
    return McpAdminService(plane)


Service = Annotated[McpAdminService, Depends(_service)]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def _quoted(etag: str | None) -> str | None:
    if etag is None:
        return None
    return etag if etag.startswith('"') else f'"{etag}"'


def _set_etag(response: Response, etag: str | None) -> None:
    quoted = _quoted(etag)
    if quoted is not None:
        response.headers["ETag"] = quoted


def build_router() -> APIRouter:
    router = APIRouter(tags=["mcp-admin"])

    @router.post("/servers", response_model=ServerView, status_code=status.HTTP_201_CREATED)
    async def register_server(
        request: Request,
        response: Response,
        body: RegisterServerBody,
        scope: ConfigScope,
        service: Service,
    ) -> ServerView:
        server = await service.register(
            scope, _correlation(request), url=body.url, display_name=body.display_name
        )
        _set_etag(response, server.etag)
        return server_view(server)

    @router.get("/servers", response_model=ServerPage)
    async def list_servers(
        scope: ConfigScope,
        service: Service,
        cursor: Annotated[str | None, Query(pattern=r"^mcp-[0-9a-f]{32}$")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> ServerPage:
        servers, next_cursor = await service.list_servers(after=cursor, limit=limit)
        return ServerPage(items=[server_view(s) for s in servers], next_cursor=next_cursor)

    @router.get("/servers/{server_id}", response_model=ServerView)
    async def get_server(
        response: Response, server_id: ServerPath, scope: ConfigScope, service: Service
    ) -> ServerView:
        server = await service.get(server_id)
        _set_etag(response, server.etag)
        return server_view(server)

    @router.patch("/servers/{server_id}", response_model=ServerView)
    async def update_server(
        request: Request,
        response: Response,
        server_id: ServerPath,
        body: UpdateServerBody,
        if_match: IfMatch,
        scope: ConfigScope,
        service: Service,
    ) -> ServerView:
        server = await service.update(
            scope,
            _correlation(request),
            server_id,
            if_match=if_match,
            display_name=body.display_name,
            status=body.status,
        )
        _set_etag(response, server.etag)
        return server_view(server)

    @router.post("/servers/{server_id}/sync", response_model=SyncView)
    async def sync_server(
        request: Request,
        response: Response,
        server_id: ServerPath,
        scope: ConfigScope,
        service: Service,
        if_match: OptionalIfMatch = None,
    ) -> SyncView:
        server, result = await service.sync(
            scope, _correlation(request), server_id, if_match=if_match
        )
        _set_etag(response, server.etag)
        return sync_view(server, result)

    @router.get("/servers/{server_id}/tools", response_model=ToolList)
    async def list_tools(
        response: Response, server_id: ServerPath, scope: ConfigScope, service: Service
    ) -> ToolList:
        server = await service.get(server_id)
        _set_etag(response, server.etag)
        return tool_list(server)

    @router.post("/servers/{server_id}/tools/{tool_name}/approval", response_model=ToolList)
    async def approve_tool(
        request: Request,
        response: Response,
        server_id: ServerPath,
        tool_name: ToolPath,
        body: ApproveToolBody,
        if_match: IfMatch,
        scope: ConfigScope,
        service: Service,
    ) -> ToolList:
        server = await service.approve(
            scope,
            _correlation(request),
            server_id,
            tool_name,
            expected_hash=body.expected_hash,
            if_match=if_match,
        )
        _set_etag(response, server.etag)
        return tool_list(server)

    @router.delete("/servers/{server_id}/tools/{tool_name}/approval", response_model=ToolList)
    async def revoke_tool(
        request: Request,
        response: Response,
        server_id: ServerPath,
        tool_name: ToolPath,
        if_match: IfMatch,
        scope: ConfigScope,
        service: Service,
        reason: Annotated[
            str, Query(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$")
        ] = DEFAULT_REVOKE_REASON,
    ) -> ToolList:
        server = await service.revoke(
            scope, _correlation(request), server_id, tool_name, reason=reason, if_match=if_match
        )
        _set_etag(response, server.etag)
        return tool_list(server)

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    registry.register(PREFIX, build_router())
