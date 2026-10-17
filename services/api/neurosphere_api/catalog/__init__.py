"""Catalog API (PRP-10 item 5); curation (item 4) lives under ``curation/``.

Public API:

* :func:`register` -- router hook (prefix ``/catalog``) for ``RouterRegistry``.
* :class:`CatalogService` -- entity create/update/deprecate/recertify, import, export and
  stale-agent reconciliation, all audited.
* ``get_graph``, ``get_service`` -- FastAPI providers tests override with
  ``app.dependency_overrides``; the repository and clock providers are curation's.

``/catalog/curation`` is a separate router; no route here can match a path under it.
"""

from neurosphere_api.catalog.dependencies import (
    EntityAccess,
    entity_access,
    get_clock,
    get_graph,
    get_repository,
    get_service,
)
from neurosphere_api.catalog.router import PREFIX, build_router, clamp_budget, register
from neurosphere_api.catalog.service import CatalogService, audit_chain_for, plan_digest

__all__ = [
    "PREFIX",
    "CatalogService",
    "EntityAccess",
    "audit_chain_for",
    "build_router",
    "clamp_budget",
    "entity_access",
    "get_clock",
    "get_graph",
    "get_repository",
    "get_service",
    "plan_digest",
    "register",
]
