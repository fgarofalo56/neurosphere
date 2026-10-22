"""``GET /api/v1/workspaces/{role}`` (PRP-28 item 1).

``role`` is a frontend persona name, mapped EXPLICITLY to a backend ``Role``. Access is decided
here from the server-derived ``IdentityScope`` (an unexpired role assignment of the mapped role);
nothing in the request names a role. Unknown persona -> 404; persona not held -> 403 ``forbidden``.

Route-inventory note: no single permission is held by all five roles (the auditor holds only
``audit.read``/``evidence.read``), so the route declares ``data.read`` for the inventory with a
marker (precedent: the realtime gateway) and authenticates via ``current_scope``; the role check
above is the real gate.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route function.
"""

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from neurosphere_core.auth.scope import Permission, Role
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import PERMISSION_MARKER, AuthzState, current_scope, get_authz_state
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


def _authenticated_marker() -> None:
    """Declares ``data.read`` for the route inventory; the role is enforced in the handler."""
    return None


setattr(_authenticated_marker, PERMISSION_MARKER, Permission.DATA_READ)


def _holds_role(scope: IdentityScope, role: Role, now: datetime) -> bool:
    for assignment in scope.to_contract().roles:
        if Role(assignment.role) is not role:
            continue
        expiry = assignment.expires_at
        if expiry is None or now < datetime.fromisoformat(expiry.root.replace("Z", "+00:00")):
            return True
    return False


def build_router() -> APIRouter:
    router = APIRouter(tags=["workspaces"])

    @router.get(
        "/{role}", response_model=WorkspaceBody, dependencies=[Depends(_authenticated_marker)]
    )
    async def workspace(
        role: str,
        scope: Annotated[IdentityScope, Depends(current_scope)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> WorkspaceBody:
        backend = ROLE_MAP.get(role)
        if backend is None:
            raise HTTPException(status_code=404, detail="unknown workspace")
        now = datetime.fromtimestamp(state.clock(), UTC)
        if not _holds_role(scope, backend, now):
            raise ForbiddenError("role not held", reason="role_not_held")
        persona = cast("Literal['viewer', 'analyst', 'steward', 'admin', 'auditor']", role)
        return WorkspaceBody(workspace=persona, items=[])

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
