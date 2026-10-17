"""Catalog curation: steward decisions, locks and re-inference handling (PRP-10 item 4).

Public API:

* :func:`register` -- router hook (prefix ``/catalog/curation``) for ``RouterRegistry``.
* :class:`CurationService` -- ``decide`` (accept, reject, override, lock, unlock) and
  ``apply_inference`` (merge a re-inferred edge; locks keep presented lineage and conflicts
  are queued).
* ``get_repository``, ``get_review_queue``, ``get_clock``, ``get_service`` -- FastAPI providers
  that tests override with ``app.dependency_overrides``.
"""

from neurosphere_api.catalog.curation.dependencies import (
    EdgeAccess,
    edge_access,
    get_clock,
    get_repository,
    get_review_queue,
    get_service,
)
from neurosphere_api.catalog.curation.router import PREFIX, build_router, register
from neurosphere_api.catalog.curation.service import (
    Clock,
    CurationService,
    DecisionResult,
    InferenceResult,
    audit_chain_id,
)

__all__ = [
    "PREFIX",
    "Clock",
    "CurationService",
    "DecisionResult",
    "EdgeAccess",
    "InferenceResult",
    "audit_chain_id",
    "build_router",
    "edge_access",
    "get_clock",
    "get_repository",
    "get_review_queue",
    "get_service",
    "register",
]
