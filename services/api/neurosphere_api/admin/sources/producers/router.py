"""Producer admin routes, mounted at ``/api/v1/admin/sources/producers`` (PRP-41 item 3).

| Method | Path                         | Notes                                              |
|--------|------------------------------|----------------------------------------------------|
| POST   | ``/``                        | 201 ``ProducerSecretIssued`` (secret shown once)   |
| GET    | ``/``                        | bounded list, no digest                            |
| GET    | ``/{producer_id}``           | ``ETag``                                           |
| POST   | ``/{producer_id}/rotate``    | ``If-Match``; new secret shown once                |
| POST   | ``/{producer_id}/disable``   | ``If-Match``                                       |
| POST   | ``/{producer_id}/enable``    | ``If-Match``                                       |

Every route needs customer-level ``config.manage`` (``require_customer_control``).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from neurosphere_contracts.admin.v1.producer_secret_issued import ProducerSecretIssued
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.customer_control import require_customer_control
from neurosphere_api.admin.sources.producers.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ProducerCreateRequest,
    ProducerPage,
    ProducerView,
    issued_response,
    producer_view,
)
from neurosphere_api.admin.sources.producers.service import (
    ProducerAdminPlane,
    ProducerAdminService,
    get_plane,
)
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/admin/sources/producers"

ControlScope = Annotated[IdentityScope, Depends(require_customer_control(Permission.CONFIG_MANAGE))]
ProducerPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
IfMatch = Annotated[str | None, Header(alias="If-Match", min_length=1, max_length=300)]


def _service(
    request: Request,
    scope: ControlScope,
    plane: Annotated[ProducerAdminPlane, Depends(get_plane)],
) -> ProducerAdminService:
    correlation = "corr-" + correlation_id_of(request.scope).replace("-", "")
    return ProducerAdminService(plane, scope, correlation)


Service = Annotated[ProducerAdminService, Depends(_service)]


def _set_etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-producers"])

    @router.post("", response_model=ProducerSecretIssued, status_code=status.HTTP_201_CREATED)
    async def create_producer(
        response: Response, body: ProducerCreateRequest, service: Service
    ) -> ProducerSecretIssued:
        result = await service.create(body)
        _set_etag(response, result.document.etag.root)
        response.headers["Cache-Control"] = "no-store"
        return issued_response(result)

    @router.get("", response_model=ProducerPage)
    async def list_producers(
        service: Service,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    ) -> ProducerPage:
        documents = await service.list(limit)
        return ProducerPage(
            items=[producer_view(d) for d in documents], truncated=len(documents) >= limit
        )

    @router.get("/{producer_id}", response_model=ProducerView)
    async def get_producer(
        response: Response, producer_id: ProducerPath, service: Service
    ) -> ProducerView:
        document = await service.get(producer_id)
        _set_etag(response, document.etag.root)
        return producer_view(document)

    @router.post("/{producer_id}/rotate", response_model=ProducerSecretIssued)
    async def rotate_producer(
        response: Response,
        producer_id: ProducerPath,
        service: Service,
        if_match: IfMatch = None,
    ) -> ProducerSecretIssued:
        result = await service.rotate(producer_id, if_match)
        _set_etag(response, result.document.etag.root)
        response.headers["Cache-Control"] = "no-store"
        return issued_response(result)

    @router.post("/{producer_id}/disable", response_model=ProducerView)
    async def disable_producer(
        response: Response,
        producer_id: ProducerPath,
        service: Service,
        if_match: IfMatch = None,
    ) -> ProducerView:
        result = await service.set_status(producer_id, "disabled", if_match)
        _set_etag(response, result.document.etag.root)
        return producer_view(result.document)

    @router.post("/{producer_id}/enable", response_model=ProducerView)
    async def enable_producer(
        response: Response,
        producer_id: ProducerPath,
        service: Service,
        if_match: IfMatch = None,
    ) -> ProducerView:
        result = await service.set_status(producer_id, "active", if_match)
        _set_etag(response, result.document.etag.root)
        return producer_view(result.document)

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    registry.register(PREFIX, build_router())
