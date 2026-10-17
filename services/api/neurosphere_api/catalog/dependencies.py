"""FastAPI dependencies for the catalog API (PRP-10 item 5).

The repository and clock providers are the ones curation already defines
(:func:`~neurosphere_api.catalog.curation.dependencies.get_repository`,
:func:`~neurosphere_api.catalog.curation.dependencies.get_clock`): one catalog, one wiring, and a
test override of either applies to both routers. This module adds:

* :func:`get_graph` -- ``app.state.catalog_graph`` (a ``GraphQuery``); fails closed with 503.
* :func:`get_service` -- the :class:`CatalogService` over the repository, audit and clock.
* :func:`entity_access` -- the per-route authorization dependency for a stored entity.

Authorization: the target domain of an entity route is the domain of the STORED entity, loaded
with the caller's scope; the path id, the body and the query string never name the domain that is
checked. A missing and an out-of-scope entity both resolve to nothing, which ``require`` answers
with the same 403.

This module deliberately has no ``from __future__ import annotations``: the dependency functions
are built in closures and FastAPI must see real annotation objects.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Path, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, GraphQuery
from neurosphere_core.catalog.repo.documents import entity_domain
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.router import get_audit_repository
from neurosphere_api.authz import AuthzTarget, current_scope, require
from neurosphere_api.catalog.curation.dependencies import get_clock, get_repository
from neurosphere_api.catalog.curation.service import Clock
from neurosphere_api.catalog.service import CatalogService

__all__ = [
    "EntityAccess",
    "entity_access",
    "get_clock",
    "get_graph",
    "get_repository",
    "get_service",
]

_STATE_KEY: Final = "catalog_entity"
_MAX_ENTITY_ID_LENGTH: Final = 512


def get_graph(request: Request) -> GraphQuery:
    graph = getattr(request.app.state, "catalog_graph", None)
    if not isinstance(graph, GraphQuery):
        raise DependencyTransientError(
            "catalog graph is not configured", reason="catalog_graph_unconfigured"
        )
    return graph


def get_service(
    repository: Annotated[CatalogRepository, Depends(get_repository)],
    clock: Annotated[Clock, Depends(get_clock)],
    audit: Annotated[AuditRepository, Depends(get_audit_repository)],
) -> CatalogService:
    return CatalogService(repository, audit, clock)


@dataclass(frozen=True, slots=True)
class EntityAccess:
    """An authorized request: the caller's scope plus the stored entity it was checked against."""

    scope: IdentityScope
    entity: CatalogEntity


async def _load_entity(
    request: Request,
    entity_id: Annotated[str, Path(max_length=_MAX_ENTITY_ID_LENGTH)],
    scope: Annotated[IdentityScope, Depends(current_scope)],
    repository: Annotated[CatalogRepository, Depends(get_repository)],
) -> CatalogEntity | None:
    """Load the entity with the caller's scope (None when missing or out of scope)."""
    entity = await repository.get_entity(scope, entity_id)
    setattr(request.state, _STATE_KEY, entity)
    return entity


def _stored_entity_target(request: Request, scope: IdentityScope) -> AuthzTarget | None:
    entity = getattr(request.state, _STATE_KEY, None)
    if entity is None:
        return None
    domain = entity_domain(entity.model_dump(mode="json"))
    return None if domain is None else AuthzTarget(domain_id=domain)


def entity_access(permission: Permission) -> Callable[..., object]:
    """Dependency factory: ``EntityAccess`` once ``permission`` holds on the stored entity's domain.

    Order is fixed here: authenticate, load the entity in scope, then ``require`` the permission
    on the loaded entity's own domain.
    """
    permitted = require(permission, resource=_stored_entity_target)

    async def authorize(
        loaded: Annotated[CatalogEntity | None, Depends(_load_entity)],
        scope: Annotated[IdentityScope, Depends(permitted)],
    ) -> EntityAccess:
        # ``permitted`` already denied when ``loaded`` is None, so this is a type narrowing only.
        if loaded is None:  # pragma: no cover - require() raised before reaching here
            raise DependencyTransientError("entity not loaded", reason="entity_not_loaded")
        return EntityAccess(scope=scope, entity=loaded)

    authorize.__name__ = f"authorize_entity_{permission.value.replace('.', '_')}"
    return authorize
