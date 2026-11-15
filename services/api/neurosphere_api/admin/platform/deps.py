"""Shared route dependencies of the platform admin API (PRP-44).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Header, Request, Response
from neurosphere_core.admin.platform import PlatformAdmin
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.customer_control import require_customer_control
from neurosphere_api.admin.platform.service import (
    PlatformAdminPlane,
    PlatformAuditor,
    get_plane,
)
from neurosphere_api.middleware import correlation_id_of

__all__ = ["PREFIX", "IfMatch", "Platform", "PlatformContext", "correlation", "set_etag"]

PREFIX: Final = "/api/v1/admin/platform"

ConfigScope = Annotated[IdentityScope, Depends(require_customer_control())]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]


@dataclass(frozen=True)
class PlatformContext:
    """The admin services, the caller's customer and the audit wrapper for one request."""

    admin: PlatformAdmin
    customer_id: str
    audit: PlatformAuditor

    @property
    def actor(self) -> str:
        return self.audit.actor


def _context(
    scope: ConfigScope, plane: Annotated[PlatformAdminPlane, Depends(get_plane)]
) -> PlatformContext:
    return PlatformContext(plane.admin, scope.customer_id, PlatformAuditor(plane, scope))


Platform = Annotated[PlatformContext, Depends(_context)]


def correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def set_etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'
