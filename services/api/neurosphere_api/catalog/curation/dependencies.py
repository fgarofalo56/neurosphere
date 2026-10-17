"""FastAPI dependencies for catalog curation (PRP-10 item 4).

Providers (tests override them with ``app.dependency_overrides``; production wiring sets the
matching ``app.state`` attribute). Each fails closed with 503 when nothing is configured:

* :func:`get_repository` -- ``app.state.catalog_repository`` (a ``CatalogRepository``).
* :func:`get_review_queue` -- ``app.state.catalog_review_queue`` (a ``ReviewQueue``).
* :func:`get_clock` -- ``app.state.catalog_clock`` or UTC now.
* :func:`get_service` -- the :class:`CurationService` built from the three above and the audit
  repository (``app.state.audit_repository``).

Authorization: :func:`edge_access` builds the per-route dependency. The target domain of a
curation or read request is resolved from the STORED edge (loaded with the caller's scope), never
from the request body or from anything the caller types. An edge that is missing or outside the
scope resolves to nothing, which ``require`` answers with the same 403 as an out-of-scope domain.

This module deliberately has no ``from __future__ import annotations``: the dependency functions
are built in closures and FastAPI must see real annotation objects.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, Path, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog.protocol import CatalogEdge, CatalogRepository
from neurosphere_core.catalog.review_queue import ReviewQueue
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.router import get_audit_repository
from neurosphere_api.authz import AuthzTarget, current_scope, require
from neurosphere_api.catalog.curation.service import Clock, CurationService

__all__ = [
    "EdgeAccess",
    "edge_access",
    "get_clock",
    "get_repository",
    "get_review_queue",
    "get_service",
]

_STATE_KEY: Final = "curation_edge"
_MAX_EDGE_ID_LENGTH: Final = 512


def get_repository(request: Request) -> CatalogRepository:
    repository = getattr(request.app.state, "catalog_repository", None)
    if not isinstance(repository, CatalogRepository):
        raise DependencyTransientError(
            "catalog repository is not configured", reason="catalog_repository_unconfigured"
        )
    return repository


def get_review_queue(request: Request) -> ReviewQueue:
    queue = getattr(request.app.state, "catalog_review_queue", None)
    if not isinstance(queue, ReviewQueue):
        raise DependencyTransientError(
            "review queue is not configured", reason="catalog_review_queue_unconfigured"
        )
    return queue


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock(request: Request) -> Clock:
    clock: Clock | None = getattr(request.app.state, "catalog_clock", None)
    return clock if callable(clock) else _utc_now


def get_service(
    repository: Annotated[CatalogRepository, Depends(get_repository)],
    queue: Annotated[ReviewQueue, Depends(get_review_queue)],
    clock: Annotated[Clock, Depends(get_clock)],
    audit: Annotated[AuditRepository, Depends(get_audit_repository)],
) -> CurationService:
    return CurationService(repository, queue, audit, clock)


@dataclass(frozen=True, slots=True)
class EdgeAccess:
    """An authorized request: the caller's scope plus the stored edge it was checked against."""

    scope: IdentityScope
    edge: CatalogEdge


async def _load_edge(
    request: Request,
    edge_id: Annotated[str, Path(max_length=_MAX_EDGE_ID_LENGTH)],
    scope: Annotated[IdentityScope, Depends(current_scope)],
    repository: Annotated[CatalogRepository, Depends(get_repository)],
) -> CatalogEdge | None:
    """Load the edge with the caller's scope (None when missing or out of scope)."""
    edge = await repository.get_edge(scope, edge_id)
    setattr(request.state, _STATE_KEY, edge)
    return edge


def _stored_edge_target(request: Request, scope: IdentityScope) -> AuthzTarget | None:
    edge = getattr(request.state, _STATE_KEY, None)
    if edge is None:
        return None
    return AuthzTarget(domain_id=edge.domain_id.root)


def edge_access(permission: Permission) -> Callable[..., object]:
    """Dependency factory: ``EdgeAccess`` once ``permission`` holds on the stored edge's domain.

    Order matters and is fixed here: authenticate, load the edge in scope, then ``require`` the
    permission on the loaded edge's own domain.
    """
    permitted = require(permission, resource=_stored_edge_target)

    async def authorize(
        loaded: Annotated[CatalogEdge | None, Depends(_load_edge)],
        scope: Annotated[IdentityScope, Depends(permitted)],
    ) -> EdgeAccess:
        # ``permitted`` already denied when ``loaded`` is None, so this is a type narrowing only.
        if loaded is None:  # pragma: no cover - require() raised before reaching here
            raise DependencyTransientError("edge not loaded", reason="edge_not_loaded")
        return EdgeAccess(scope=scope, edge=loaded)

    authorize.__name__ = f"authorize_{permission.value.replace('.', '_')}"
    return authorize
