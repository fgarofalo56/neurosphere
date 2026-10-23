"""MCP registration admin (PRP-22 item 3): register external servers, sync, approve, revoke.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/mcp/admin``) for ``RouterRegistry``.
* :func:`configure_mcp_admin` -- installs the :class:`McpAdminPlane` (registry, external client,
  audit repository) on ``app.state``; unset -> 503.

Every route requires ``config.manage``; every change is audited on the ``<customer>.mcp-admin``
chain. Item 2's registry and client do the work; this package adds authorization, audit and HTTP.
"""

from neurosphere_api.mcp.admin.models import (
    ApproveToolBody,
    RegisterServerBody,
    ServerPage,
    ServerView,
    SyncView,
    ToolChangeView,
    ToolEntryView,
    ToolList,
    ToolView,
    UpdateServerBody,
)
from neurosphere_api.mcp.admin.router import (
    PREFIX,
    STATE_ATTRIBUTE,
    build_router,
    configure_mcp_admin,
    register,
)
from neurosphere_api.mcp.admin.service import (
    CHAIN_SUFFIX,
    McpAdminPlane,
    McpAdminService,
    audit_chain_id,
)

__all__ = [
    "CHAIN_SUFFIX",
    "PREFIX",
    "STATE_ATTRIBUTE",
    "ApproveToolBody",
    "McpAdminPlane",
    "McpAdminService",
    "RegisterServerBody",
    "ServerPage",
    "ServerView",
    "SyncView",
    "ToolChangeView",
    "ToolEntryView",
    "ToolList",
    "ToolView",
    "UpdateServerBody",
    "audit_chain_id",
    "build_router",
    "configure_mcp_admin",
    "register",
]
