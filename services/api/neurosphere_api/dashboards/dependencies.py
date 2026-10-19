"""FastAPI providers for the dashboards API (PRP-14 item 2).

* :func:`get_aggregate_reader` -- ``app.state.aggregate_reader`` (an ``AggregateReader``); fails
  closed with 503 when unset. Tests use ``app.dependency_overrides``.
* :func:`get_analytics_probe` -- optional ``app.state.analytics_adapter``,
  ``analytics_region`` and ``analytics_health``; absent values are fine (state ``disabled``).
* :func:`get_clock` -- UTC now, overridable in tests.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.errors import DependencyTransientError

from neurosphere_api.dashboards.analytics import AnalyticsProbe

__all__ = ["Clock", "get_aggregate_reader", "get_analytics_probe", "get_clock"]

Clock = Callable[[], datetime]


def get_aggregate_reader(request: Request) -> AggregateReader:
    reader = getattr(request.app.state, "aggregate_reader", None)
    if not isinstance(reader, AggregateReader):
        raise DependencyTransientError(
            "aggregate reader is not configured", reason="aggregates_unconfigured"
        )
    return reader


def get_analytics_probe(request: Request) -> AnalyticsProbe:
    state = request.app.state
    region = getattr(state, "analytics_region", None)
    health = getattr(state, "analytics_health", None)
    return AnalyticsProbe(
        adapter=getattr(state, "analytics_adapter", None),
        region=region if isinstance(region, str) else None,
        health=health if callable(health) else None,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return _utc_now
