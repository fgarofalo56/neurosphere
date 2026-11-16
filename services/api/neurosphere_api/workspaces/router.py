"""``GET /api/v1/workspaces/{role}`` (PRP-28 item 1; role gate PRP-48 item 1, #91).

``role`` is a frontend persona name, mapped EXPLICITLY to a backend ``Role``. Access is decided
from the server-derived ``IdentityScope`` by :func:`neurosphere_api.authz.require_role`: an
unexpired assignment of the mapped role that names at least one domain in the scope's allowed
domains (an assignment naming only another customer's domain confers nothing). Nothing in the
request names a role. Unknown persona -> 404; persona not held -> 403 ``forbidden`` reason
``role_not_held``, recorded by the denial recorder.

Route inventory: the route is in the role-gated category (``authz.routes.ROLE_GATED_PATHS``) and
claims no permission; no single permission is held by all five roles.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route function.
"""

from types import MappingProxyType
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import Role
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require_role
from neurosphere_api.routers import RouterRegistry
from neurosphere_api.workspaces.models import WorkspaceBody

__all__ = ["PREFIX", "ROLE_MAP", "build_router", "register"]

PREFIX: Final = "/api/v1/workspaces"

ROLE_MAP: Final = MappingProxyType(
    {
        "viewer": Role.VIEWER,
        "analyst": Role.ANALYST,
        "steward": Role.DOMAIN_STEWARD,
        "admin": Role.ADMIN,
        "auditor": Role.SECURITY_AUDITOR,
    }
)


def _role_from_path(request: Request) -> Role | None:
    persona = request.path_params.get("role")
    return ROLE_MAP.get(persona) if isinstance(persona, str) else None


def build_router() -> APIRouter:
    router = APIRouter(tags=["workspaces"])

    @router.get("/{role}", response_model=WorkspaceBody)
    async def workspace(
        role: str,
        scope: Annotated[IdentityScope, Depends(require_role(_role_from_path))],
    ) -> WorkspaceBody:
        persona = cast("Literal['viewer', 'analyst', 'steward', 'admin', 'auditor']", role)
        return WorkspaceBody(workspace=persona, items=[])

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
