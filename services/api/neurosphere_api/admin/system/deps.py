"""Shared dependencies of the system admin routes (PRP-45).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import Depends, Header, Request, Response
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.deployment_scope import require_deployment_admin
from neurosphere_api.middleware import correlation_id_of

__all__ = ["PREFIX", "AdminScope", "IfMatch", "correlation", "set_etag"]

PREFIX: Final = "/api/v1/admin/system"

#: Deployment-scoped admin: ``config.manage`` on the customer's control domain (reads too).
AdminScope = Annotated[IdentityScope, Depends(require_deployment_admin(Permission.CONFIG_MANAGE))]
IfMatch = Annotated[str | None, Header(alias="If-Match", max_length=300)]


def correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def set_etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'
