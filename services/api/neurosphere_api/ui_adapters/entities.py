"""Domain-path catalog entity writes for the browser (PRP-31 item 13), added to the
``/api/v1/catalog/domains`` router.

| Method | Path                                         | Permission                         |
|--------|----------------------------------------------|------------------------------------|
| POST   | ``/{domain}/entities``                       | ``catalog.curate`` on ``{domain}`` |
| PUT    | ``/{domain}/entities/{entity_id}`` (If-Match) | ``catalog.curate`` on ``{domain}`` |

The PRP-10 write routes (``POST``/``PUT /api/v1/catalog/entities``) take the whole entity
document, including ``cloud``, ``customer_id`` and ``domain_id``, which the browser ``ApiClient``
refuses to send. These adapters take the document WITHOUT any server-owned key (a body naming one
is 422, see :data:`~neurosphere_api.ui_adapters.models.SERVER_OWNED_ENTITY_KEYS`) and stamp them:

* ``cloud`` and ``customer_id`` from the caller's scope, ``domain_id`` from the path (checked by
  ``require`` before anything else runs, so a caller without ``catalog.curate`` on ``{domain}``
  gets 403 without schema feedback);
* on create, ``id`` is minted as ``<cloud>:<customer>:manual:<entity_type>:<uuid4 hex>``. The
  slug is server-generated, never caller-chosen, so an id collision can never reveal an entity
  in a domain the caller cannot read.

Then the PRP-10 ``CatalogService.create``/``update`` run with ``channel="button"``: versioning,
ETag, timestamps, contract validation and before/after audit stay theirs.

PUT loads the stored entity with the caller's scope; one that is missing, out of scope or not in
``{domain}`` is 404 (after the permission check on ``{domain}``, so 404 never tells a caller more
than a curator of ``{domain}`` could learn). ``entity_type`` must equal the stored type (422). A
missing ``If-Match`` is 422 and a stale one 409 ``stale_version``, exactly as on the PRP-10 route.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response, status
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, CatalogRepository
from neurosphere_core.catalog.repo.documents import dump, entity_domain
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.catalog.curation.router import audit_correlation_id
from neurosphere_api.catalog.dependencies import get_repository, get_service
from neurosphere_api.catalog.router import expected_etag
from neurosphere_api.catalog.service import CatalogService
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.ui_adapters.catalog import DomainPath
from neurosphere_api.ui_adapters.models import (
    CatalogEntityCreateRequest,
    CatalogEntityUpdateRequest,
)

__all__ = ["ID_SOURCE", "add_routes", "mint_entity_id"]

#: Source segment of a canonical id minted for an entity created in the UI.
ID_SOURCE: Final = "manual"

CurateScope = Annotated[
    IdentityScope, Depends(require(Permission.CATALOG_CURATE, domain_from_path("domain")))
]
EntityIdPath = Annotated[str, Path(min_length=1, max_length=512)]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
Service = Annotated[CatalogService, Depends(get_service)]


def mint_entity_id(scope: IdentityScope, entity_type: str) -> str:
    """A fresh canonical id ``<cloud>:<customer>:manual:<entity_type>:<uuid4 hex>``."""
    return f"{scope.cloud}:{scope.customer_id}:{ID_SOURCE}:{entity_type}:{uuid.uuid4().hex}"


def _quoted(etag: str) -> str:
    return etag if etag.startswith('"') else f'"{etag}"'


def _correlation(request: Request) -> str:
    return audit_correlation_id(correlation_id_of(request.scope))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def add_routes(router: APIRouter) -> None:
    """Add the entity create and update routes to the ``/api/v1/catalog/domains`` router."""

    @router.post(
        "/{domain}/entities",
        response_model=CatalogEntity,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_entity_in_domain(
        request: Request,
        response: Response,
        domain: DomainPath,
        body: CatalogEntityCreateRequest,
        scope: CurateScope,
        service: Service,
    ) -> CatalogEntity:
        doc = body.document()
        doc.update(
            id=mint_entity_id(scope, body.entity_type),
            cloud=scope.cloud,
            customer_id=scope.customer_id,
            domain_id=domain,
        )
        entity = await service.create(
            scope, doc, correlation_id=_correlation(request), channel="button"
        )
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity

    @router.put("/{domain}/entities/{entity_id:path}", response_model=CatalogEntity)
    async def update_entity_in_domain(
        request: Request,
        response: Response,
        domain: DomainPath,
        entity_id: EntityIdPath,
        body: CatalogEntityUpdateRequest,
        if_match: IfMatch,
        scope: CurateScope,
        repository: Repository,
        service: Service,
    ) -> CatalogEntity:
        stored = await repository.get_entity(scope, entity_id)
        if stored is None or entity_domain(dump(stored)) != domain:
            raise _not_found()
        if body.entity_type != stored.entity_type:
            raise InvalidSchemaError("entity_type cannot change", reason="entity_type_immutable")
        entity = await service.update(
            scope,
            stored,
            body.document(),
            expected_etag(if_match, stored.etag.root),
            correlation_id=_correlation(request),
            channel="button",
        )
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity
