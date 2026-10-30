"""UI-facing API adapters (PRP-31 item 2): thin, permission-checked reads and one decision route
over existing services, shaped so the browser never sends a scope key, an actor or a chain id.

Public API:

* :func:`register` -- router hook for ``RouterRegistry``. It registers three prefixes:

  - ``/api/v1/catalog/domains`` -- entity list, search and export with the domain in the path
    (:mod:`.catalog`), plus the steward decision route (:mod:`.curation`);
  - ``/api/v1/audit/domains`` -- auditable domains, records and chain verification (:mod:`.audit`);
  - ``/api/v1/capabilities`` -- the shipped capability matrix (:mod:`.capabilities`).

No storage and no permission constant is added here; every route declares an existing permission
through ``require`` and the route inventory checks it.
"""

from fastapi import APIRouter

from neurosphere_api.routers import RouterRegistry
from neurosphere_api.ui_adapters import audit, capabilities, catalog, curation

__all__ = ["PREFIXES", "build_catalog_router", "register"]

PREFIXES: tuple[str, ...] = (catalog.PREFIX, audit.PREFIX, capabilities.PREFIX)


def build_catalog_router() -> APIRouter:
    """The ``/api/v1/catalog/domains`` router: catalog reads plus the decision route."""
    router = catalog.build_router()
    curation.add_routes(router)
    return router


def register(registry: RouterRegistry) -> None:
    registry.register(catalog.PREFIX, build_catalog_router())
    registry.register(audit.PREFIX, audit.build_router())
    registry.register(capabilities.PREFIX, capabilities.build_router())
