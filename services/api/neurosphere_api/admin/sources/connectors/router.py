"""Connector configuration admin routes, mounted at ``/api/v1/admin/sources/connectors`` (PRP-42).

| Method | Path                      | Notes                                   |
|--------|---------------------------|-----------------------------------------|
| POST   | ``""``                    | create (201, ``ETag``)                  |
| GET    | ``""``                    | list, optional ``connector_kind``       |
| GET    | ``/{config_id}``          | read (``ETag``)                         |
| PUT    | ``/{config_id}``          | replace, ``If-Match`` required          |
| POST   | ``/{config_id}/enable``   | ``If-Match`` required                   |
| POST   | ``/{config_id}/disable``  | ``If-Match`` required                   |
| DELETE | ``/{config_id}``          | retire, ``If-Match`` required           |

Every route needs customer-level ``config.manage`` (``require_customer_control``): a connector
applies to the whole customer. A caller without it gets 403 and a denial record. A stored config
applies when the worker roles next start (no hot reload).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.customer_control import require_customer_control
from neurosphere_api.admin.sources.connectors.models import (
    MAX_PAGE_LIMIT,
    ConnectorPage,
    ConnectorView,
    view,
)
from neurosphere_api.admin.sources.connectors.service import (
    ConnectorAdminPlane,
    ConnectorAdminService,
    get_plane,
)
from neurosphere_api.middleware import correlation_id_of

__all__ = ["PREFIX", "build_router"]

PREFIX: Final = "/api/v1/admin/sources/connectors"

ConfigScope = Annotated[IdentityScope, Depends(require_customer_control())]
ConfigPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
Kind = Annotated[
    str | None, Query(pattern=r"^(gateway_poll|foundry_discovery|billing_export|otel)$")
]


def _service(
    scope: ConfigScope, plane: Annotated[ConnectorAdminPlane, Depends(get_plane)]
) -> ConnectorAdminService:
    return ConnectorAdminService(plane, scope)


Service = Annotated[ConnectorAdminService, Depends(_service)]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def _etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-connectors"])

    @router.post("", response_model=ConnectorView, status_code=status.HTTP_201_CREATED)
    async def create_connector(
        request: Request, response: Response, body: ConnectorConfig, service: Service
    ) -> ConnectorView:
        write = await service.create(_correlation(request), body)
        _etag(response, write.document.etag.root)
        return view(write.document, write.warnings)

    @router.get("", response_model=ConnectorPage)
    async def list_connectors(
        service: Service,
        connector_kind: Kind = None,
        include_retired: bool = False,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = 50,
    ) -> ConnectorPage:
        documents = await service.list(
            connector_kind=connector_kind, include_retired=include_retired, limit=limit
        )
        return ConnectorPage(items=[view(d) for d in documents])

    @router.get("/{config_id}", response_model=ConnectorView)
    async def get_connector(
        response: Response, config_id: ConfigPath, service: Service
    ) -> ConnectorView:
        document = await service.get(config_id)
        _etag(response, document.etag.root)
        return view(document)

    @router.put("/{config_id}", response_model=ConnectorView)
    async def replace_connector(
        request: Request,
        response: Response,
        config_id: ConfigPath,
        body: ConnectorConfig,
        if_match: IfMatch,
        service: Service,
    ) -> ConnectorView:
        write = await service.replace(_correlation(request), config_id, body, if_match)
        _etag(response, write.document.etag.root)
        return view(write.document, write.warnings)

    @router.post("/{config_id}/enable", response_model=ConnectorView)
    async def enable_connector(
        request: Request,
        response: Response,
        config_id: ConfigPath,
        if_match: IfMatch,
        service: Service,
    ) -> ConnectorView:
        write = await service.set_enabled(_correlation(request), config_id, True, if_match)
        _etag(response, write.document.etag.root)
        return view(write.document, write.warnings)

    @router.post("/{config_id}/disable", response_model=ConnectorView)
    async def disable_connector(
        request: Request,
        response: Response,
        config_id: ConfigPath,
        if_match: IfMatch,
        service: Service,
    ) -> ConnectorView:
        write = await service.set_enabled(_correlation(request), config_id, False, if_match)
        _etag(response, write.document.etag.root)
        return view(write.document, write.warnings)

    @router.delete("/{config_id}", response_model=ConnectorView)
    async def retire_connector(
        request: Request,
        response: Response,
        config_id: ConfigPath,
        if_match: IfMatch,
        service: Service,
    ) -> ConnectorView:
        document = await service.retire(_correlation(request), config_id, if_match)
        _etag(response, document.etag.root)
        return view(document)

    return router
