"""Source status routes (PRP-139 item 3).

| Method | Path                            | Who                                          |
|--------|---------------------------------|----------------------------------------------|
| GET    | ``/api/v1/sources/status``      | any caller who can read at least one domain  |
| GET    | ``/api/v1/admin/sources/status``| customer-level ``config.manage``             |

The first answers the four sources with a state and a last success time only (no reason, no
count, no id, name or host). The second adds the reason code per source and the run status and
counts per connector kind. A caller who reads no domain, or whose roles have expired, gets 403
and a denial record from ``require``; a domain admin without the customer control domain gets
403 ``customer_scope_required``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.customer_control import require_customer_control
from neurosphere_api.authz import require
from neurosphere_api.sources_status.models import (
    SourcesAdminListView,
    SourceStatusListView,
    admin_view,
    user_view,
)
from neurosphere_api.sources_status.service import (
    SourceStatusPlane,
    get_plane,
    read_summary,
)

__all__ = ["ADMIN_PREFIX", "USER_PREFIX", "build_admin_router", "build_user_router"]

USER_PREFIX: Final = "/api/v1/sources"
ADMIN_PREFIX: Final = "/api/v1/admin/sources/status"

_read_anywhere = require(Permission.DATA_READ)
_customer_admin = require_customer_control()

Plane = Annotated[SourceStatusPlane, Depends(get_plane)]

_USER_DESCRIPTION: Final = (
    "The four data sources (Foundry, API Management gateway, billing, Application Insights "
    "telemetry) with a state (`not_connected`, `connected_no_data`, `connected`, `failing`) and "
    "the last success time. Any caller who can read at least one domain; no reason, count, id, "
    "name or host. Application Insights telemetry is always `not_connected` with "
    "`available: false`."
)
_ADMIN_DESCRIPTION: Final = (
    "The source summary plus a reason code per source and the run status, last attempt time and "
    "counts per connector kind. Customer-level `config.manage` only."
)


def build_user_router() -> APIRouter:
    router = APIRouter(tags=["sources-status"])

    @router.get("/status", response_model=SourceStatusListView, description=_USER_DESCRIPTION)
    async def source_status(
        request: Request,
        scope: Annotated[IdentityScope, Depends(_read_anywhere)],
        plane: Plane,
    ) -> SourceStatusListView:
        return user_view(await read_summary(request, scope, plane))

    return router


def build_admin_router() -> APIRouter:
    router = APIRouter(tags=["sources-status"])

    @router.get("", response_model=SourcesAdminListView, description=_ADMIN_DESCRIPTION)
    async def admin_source_status(
        request: Request,
        scope: Annotated[IdentityScope, Depends(_customer_admin)],
        plane: Plane,
    ) -> SourcesAdminListView:
        return admin_view(await read_summary(request, scope, plane))

    return router
