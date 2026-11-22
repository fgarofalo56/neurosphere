"""Agent identity routes (PRP-137 item 5).

PUT  /api/v1/agent-identity/domains/{domain}/aliases  needs catalog.curate in {domain}
GET  /api/v1/agent-identity/domains/{domain}/aliases  needs data.read in {domain}

A viewer, auditor, steward of another domain or caller with an expired role gets 403 and a denial
record from ``require``. A target agent that is missing, out of scope or in another domain is the
same 404.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.agent_identity.models import (
    AliasDeclareRequest,
    AliasDeclareView,
    AliasView,
)
from neurosphere_api.agent_identity.service import (
    AgentIdentityPlane,
    AgentIdentityService,
    get_plane,
)
from neurosphere_api.audit.router import get_audit_repository
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.catalog.curation.dependencies import get_clock
from neurosphere_api.catalog.curation.router import audit_correlation_id
from neurosphere_api.catalog.curation.service import Clock
from neurosphere_api.middleware import correlation_id_of

__all__ = ["PREFIX", "build_router"]

PREFIX: Final = "/api/v1/agent-identity"

_curate = require(Permission.CATALOG_CURATE, domain_from_path("domain"))
_read = require(Permission.DATA_READ, domain_from_path("domain"))

Domain = Annotated[str, Path(min_length=1, max_length=512)]
SourceId = Annotated[str, Query(min_length=1, max_length=128)]
ExternalId = Annotated[str, Query(min_length=1, max_length=512)]


def get_service(
    plane: Annotated[AgentIdentityPlane, Depends(get_plane)],
    audit: Annotated[AuditRepository, Depends(get_audit_repository)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AgentIdentityService:
    return AgentIdentityService(plane.repository, audit, clock)


Service = Annotated[AgentIdentityService, Depends(get_service)]

_PUT_DESCRIPTION: Final = (
    "Declare (or repoint) the alias from an external agent id seen in telemetry to a catalog "
    "agent of this domain. A previous active alias for the same key is retired first. "
    "`reresolve_needed` is true when events already processed must be re-resolved with the "
    "returned operator job (`python -m neurosphere_workers.agent_identity reresolve`)."
)


def build_router() -> APIRouter:
    router = APIRouter(tags=["agent-identity"])

    @router.put(
        "/domains/{domain}/aliases",
        response_model=AliasDeclareView,
        description=_PUT_DESCRIPTION,
    )
    async def declare_alias(
        request: Request,
        domain: Domain,
        body: AliasDeclareRequest,
        scope: Annotated[IdentityScope, Depends(_curate)],
        service: Service,
    ) -> AliasDeclareView:
        return await service.declare(
            scope,
            domain,
            body,
            correlation_id=audit_correlation_id(correlation_id_of(request.scope)),
        )

    @router.get("/domains/{domain}/aliases", response_model=AliasView)
    async def read_alias(
        domain: Domain,
        source_id: SourceId,
        external_agent_id: ExternalId,
        scope: Annotated[IdentityScope, Depends(_read)],
        service: Service,
    ) -> AliasView:
        return await service.lookup(scope, domain, source_id, external_agent_id)

    return router
