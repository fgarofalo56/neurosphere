"""Domain registry routes, mounted at ``/api/v1/admin/platform/domains`` (PRP-44).

| Method | Path                    | Notes                                              |
|--------|-------------------------|----------------------------------------------------|
| POST   | ``""``                  | create (201, ``ETag``); 409 on a duplicate         |
| GET    | ``""``                  | list, ``include_retired``                          |
| GET    | ``/{domain_id}``        | read (``ETag``)                                    |
| POST   | ``/{domain_id}/retire`` | ``If-Match`` required; never the control domain   |

Every route needs customer-level ``config.manage``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response, status
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.errors import NotFoundError

from neurosphere_api.admin.platform.deps import IfMatch, Platform, correlation, set_etag
from neurosphere_api.admin.platform.models import (
    MAX_PAGE_LIMIT,
    DomainPage,
    DomainView,
    domain_view,
)

DomainPath = Annotated[
    str,
    Path(
        max_length=512,
        pattern=r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._=-]+$",
    ),
]


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-platform-domains"])

    @router.post("", response_model=DomainView, status_code=status.HTTP_201_CREATED)
    async def create_domain(
        request: Request, response: Response, body: DomainDefinition, platform: Platform
    ) -> DomainView:
        write = await platform.audit.run(
            correlation(request),
            "domain.create",
            "domain",
            body.domain_id.root,
            lambda: platform.admin.domains.create(
                platform.customer_id, body, updated_by=platform.actor
            ),
            info=lambda w: (
                w.document.etag.root,
                {"version": w.document.version.root, "control_registered": w.control_registered},
            ),
        )
        set_etag(response, write.document.etag.root)
        return domain_view(write.document, control_registered=write.control_registered)

    @router.get("", response_model=DomainPage)
    async def list_domains(
        platform: Platform,
        include_retired: bool = False,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = 50,
    ) -> DomainPage:
        documents = await platform.admin.domains.list(
            platform.customer_id, include_retired=include_retired, limit=limit
        )
        return DomainPage(items=[domain_view(d) for d in documents])

    @router.get("/{domain_id}", response_model=DomainView)
    async def get_domain(
        response: Response, domain_id: DomainPath, platform: Platform
    ) -> DomainView:
        document = await platform.admin.domains.get(platform.customer_id, domain_id)
        if document is None:
            raise NotFoundError("no such domain", reason="domain_not_found")
        set_etag(response, document.etag.root)
        return domain_view(document)

    @router.post("/{domain_id}/retire", response_model=DomainView)
    async def retire_domain(
        request: Request,
        response: Response,
        domain_id: DomainPath,
        if_match: IfMatch,
        platform: Platform,
    ) -> DomainView:
        document = await platform.audit.run(
            correlation(request),
            "domain.retire",
            "domain",
            domain_id,
            lambda: platform.admin.domains.retire(
                platform.customer_id, domain_id, if_match=if_match, updated_by=platform.actor
            ),
            info=lambda d: (d.etag.root, {"version": d.version.root}),
        )
        set_etag(response, document.etag.root)
        return domain_view(document)

    return router
