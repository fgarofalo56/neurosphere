"""Dashboards API (PRP-14 item 2): cost, latency, errors and coverage from hot aggregates.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/dashboards``) for ``RouterRegistry``.
* :func:`get_aggregate_reader` -- provider reading ``app.state.aggregate_reader`` (503 when
  unset); tests override it with ``app.dependency_overrides``.
* :func:`get_analytics_probe` -- optional ``app.state.analytics_adapter`` /
  ``analytics_region`` / ``analytics_health``; absent means analytics state ``disabled``.

The router reads only ``neurosphere_core.aggregates``; it never reads the ledger or the analytics
adapter on the request path.
"""

from neurosphere_api.dashboards.dependencies import (
    get_aggregate_reader,
    get_analytics_probe,
    get_clock,
)
from neurosphere_api.dashboards.router import PREFIX, build_router, register

__all__ = [
    "PREFIX",
    "build_router",
    "get_aggregate_reader",
    "get_analytics_probe",
    "get_clock",
    "register",
]
