"""Interaction explorer routes (PRP-104), mounted at ``/api/v1/domains``.

| Method | Path                                                         | Permission         |
|--------|--------------------------------------------------------------|--------------------|
| GET    | ``/{domain_id}/interactions``                                | ``data.read``      |
| GET    | ``/{domain_id}/interactions/{interaction_id}``               | ``data.read``      |
| POST   | ``/{domain_id}/interactions/{interaction_id}/content-reads`` | ``interaction.read`` |

The path domain is the authorization TARGET (403 with a denial record outside it); the customer
comes only from the derived ``IdentityScope``. Each allowed read appends one allowed-read record
(``audited_read``: ``interaction.search``, ``interaction.metadata_read``). The search filters map
to core ``InteractionQuery`` (``from`` inclusive, ``to`` exclusive on ``captured_at``); the page is
bounded by ``MAX_QUERY_PAGE_SIZE`` and continues through an opaque ``continuation`` token.
Responses are PRP-99 ``InteractionRecord`` metadata: there is no content field. Explorer not
configured -> 503 ``interaction_explorer_unconfigured``.

The content-reads route (item 3) is the only route that returns captured content: body PRP-99
``InteractionAccessPurpose``, response the stored ``RedactedContent`` with
``Cache-Control: no-store``, through :class:`~neurosphere_api.interactions.content.
InteractionContentReader` (purpose, authorization, fail-closed ``interaction.read`` record, then
decrypt). ``require(interaction.read)`` gates the route first; the reader re-checks.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response
from neurosphere_contracts.interactions.v1.interaction_access_purpose import (
    InteractionAccessPurpose,
)
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.auth.scope import Permission
from neurosphere_core.interactions import MAX_QUERY_PAGE_SIZE
from neurosphere_core.interactions.models import DEFAULT_QUERY_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.authz.read_audit import ReadAudit, audited_read
from neurosphere_api.authz.state import AuthzState, get_authz_state
from neurosphere_api.interactions.content import ContentAccess, InteractionContentReader
from neurosphere_api.interactions.models import InteractionPage
from neurosphere_api.interactions.service import (
    Explorer,
    InteractionExplorerService,
    InteractionSearch,
)
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/domains"

_DOMAIN = domain_from_path("domain_id")
_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_CURSOR = r"^[A-Za-z0-9_\-=.~]+$"
_CATEGORY = r"^[a-z0-9][a-z0-9._-]{0,63}$"

SearchRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.DATA_READ, "interaction.search", _DOMAIN))
]
MetadataRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.DATA_READ, "interaction.metadata_read", _DOMAIN))
]
ContentScope = Annotated[IdentityScope, Depends(require(Permission.INTERACTION_READ, _DOMAIN))]
Authz = Annotated[AuthzState, Depends(get_authz_state)]
PurposeBody = Annotated[InteractionAccessPurpose, Body()]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
InteractionPath = Annotated[str, Path(pattern=_UUID)]
IdQuery = Annotated[str | None, Query(min_length=1, max_length=512)]
CategoryQuery = Annotated[str | None, Query(pattern=_CATEGORY)]
FromQuery = Annotated[
    datetime | None,
    Query(alias="from", description="Inclusive lower bound on captured_at (timezone-aware)."),
]
ToQuery = Annotated[
    datetime | None,
    Query(alias="to", description="Exclusive upper bound on captured_at (timezone-aware)."),
]
PageSizeQuery = Annotated[int, Query(ge=1, le=MAX_QUERY_PAGE_SIZE)]
ContinuationQuery = Annotated[str | None, Query(min_length=1, max_length=16384, pattern=_CURSOR)]


def build_router() -> APIRouter:
    router = APIRouter(tags=["interactions"])

    @router.get("/{domain_id}/interactions", response_model=InteractionPage)
    async def search_interactions(
        domain_id: DomainPath,
        audit: SearchRead,
        explorer: Explorer,
        agent_id: IdQuery = None,
        principal_id: IdQuery = None,
        tool_id: IdQuery = None,
        data_asset_id: IdQuery = None,
        detected_category: CategoryQuery = None,
        captured_from: FromQuery = None,
        captured_before: ToQuery = None,
        page_size: PageSizeQuery = DEFAULT_QUERY_PAGE_SIZE,
        continuation: ContinuationQuery = None,
    ) -> InteractionPage:
        search = InteractionSearch(
            agent_id=agent_id,
            principal_id=principal_id,
            tool_id=tool_id,
            data_asset_id=data_asset_id,
            detected_category=detected_category,
            captured_from=captured_from,
            captured_before=captured_before,
            page_size=page_size,
            continuation=continuation,
        )
        page = await InteractionExplorerService(explorer).search(audit.scope, domain_id, search)
        await audit.allowed([domain_id], len(page.items))
        return page

    @router.get("/{domain_id}/interactions/{interaction_id}", response_model=InteractionRecord)
    async def get_interaction(
        domain_id: DomainPath,
        interaction_id: InteractionPath,
        audit: MetadataRead,
        explorer: Explorer,
    ) -> InteractionRecord:
        record = await InteractionExplorerService(explorer).get(
            audit.scope, domain_id, interaction_id
        )
        await audit.allowed([domain_id], 1)
        return record

    @router.post(
        "/{domain_id}/interactions/{interaction_id}/content-reads",
        response_model=RedactedContent,
    )
    async def read_interaction_content(
        domain_id: DomainPath,
        interaction_id: InteractionPath,
        purpose: PurposeBody,
        scope: ContentScope,
        explorer: Explorer,
        authz: Authz,
        request: Request,
        response: Response,
    ) -> RedactedContent:
        response.headers["Cache-Control"] = "no-store"
        access = ContentAccess(
            scope=scope,
            now=datetime.fromtimestamp(authz.clock(), UTC),
            request_id=correlation_id_of(request.scope),
            method=request.method,
            path=request.url.path,
            denials=authz.denial_recorder,
        )
        return await InteractionContentReader(explorer).read(
            access, domain_id, interaction_id, purpose
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
