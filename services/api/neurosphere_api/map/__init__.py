"""Bounded map viewport API (PRP-18 item 2).

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/map``) for ``RouterRegistry``.
* :func:`build_router` -- the router (``GET /domains/{domain_id}/viewport``).
* Providers reading ``app.state`` (503 when unset): :func:`get_graph` (``catalog_graph``),
  :func:`get_repository` (``catalog_repository``), :func:`get_aggregate_reader`
  (``aggregate_reader``), :func:`get_pseudonymizer` (``map_pseudonymizer``); optional
  ``map_viewport_limits`` (:class:`ViewportLimits`).
* :data:`MAX_VIEWPORT_NODES` -- the 2000-node server ceiling.
* The response models of the wire contract.
"""

from neurosphere_api.map.dependencies import (
    MAX_VIEWPORT_EDGES,
    MAX_VIEWPORT_NODES,
    ViewportLimits,
    get_aggregate_reader,
    get_clock,
    get_graph,
    get_limits,
    get_pseudonymizer,
    get_repository,
)
from neurosphere_api.map.models import (
    Coverage,
    NodeMetrics,
    ViewportEdge,
    ViewportNode,
    ViewportResponse,
)
from neurosphere_api.map.router import PREFIX, build_router, register

__all__ = [
    "MAX_VIEWPORT_EDGES",
    "MAX_VIEWPORT_NODES",
    "PREFIX",
    "Coverage",
    "NodeMetrics",
    "ViewportEdge",
    "ViewportLimits",
    "ViewportNode",
    "ViewportResponse",
    "build_router",
    "get_aggregate_reader",
    "get_clock",
    "get_graph",
    "get_limits",
    "get_pseudonymizer",
    "get_repository",
    "register",
]
