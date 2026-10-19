"""Analytics state for the dashboards response: ``available``, ``delayed`` or ``disabled``.

The dashboards are served from hot aggregates and never need the analytics adapter. This module
only REPORTS the adapter's state next to the data, so a stopped, failing or absent adapter changes
the badge and never the status code.

Inputs, all optional and all read from ``app.state`` by the dependency:

* the adapter (``AnalyticsAdapter``): absent means no backend is enabled -> ``disabled``;
* its ``cloud`` and a region, checked against the capability matrix (``list_backends``): a backend
  the matrix disables for that cloud/region is ``disabled``; an unverifiable one is ``disabled``
  too (fail closed);
* a health probe (an ``adapter.health()`` or ``app.state.analytics_health`` callable, sync or
  async, returning ``False`` for stopped): stopped -> ``disabled``; raising or timing out ->
  ``delayed``;
* the aggregate lag: beyond ``LAG_DELAYED_SECONDS`` (or nothing applied yet) -> ``delayed``.

Reason strings are generic on purpose: no vendor is named in anything a user sees.
"""

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from neurosphere_core.analytics.base import list_backends

from neurosphere_api.dashboards.models import AnalyticsInfo

__all__ = ["HEALTH_TIMEOUT_SECONDS", "LAG_DELAYED_SECONDS", "AnalyticsProbe", "resolve_analytics"]

LAG_DELAYED_SECONDS: Final = 900.0
HEALTH_TIMEOUT_SECONDS: Final = 2.0

HealthCheck = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class AnalyticsProbe:
    """What the dependency found on ``app.state``; every field may be absent."""

    adapter: object | None = None
    region: str | None = None
    health: HealthCheck | None = None


def _matrix_reason(adapter: object, region: str | None) -> str | None:
    """A reason when the capability matrix does not support the adapter's backend, else None."""
    backend = getattr(adapter, "backend", None)
    cloud = getattr(adapter, "cloud", None)
    if not isinstance(backend, str) or not isinstance(cloud, str):
        return "the analytics backend could not be identified"
    if backend == "fixture":
        return None  # sandbox-only backend, not matrix-gated
    if region is None:
        return "the analytics backend region could not be verified"
    try:
        statuses = list_backends(cloud=cloud, region=region)
    except Exception:
        return "the analytics backend availability could not be verified"
    for status in statuses:
        if status.name == backend:
            if status.status == "supported":
                return None
            return "the analytics backend is not available for this cloud and region"
    return "the analytics backend is not a recognized option"


async def _probe_health(health: HealthCheck) -> bool | None:
    """True/None healthy, False stopped. Raises on failure or timeout."""
    async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
        outcome = health()
        if inspect.isawaitable(outcome):
            outcome = await outcome
    return None if outcome is None else bool(outcome)


async def resolve_analytics(probe: AnalyticsProbe, lag_seconds: float | None) -> AnalyticsInfo:
    """Never raises: any failure of the probe itself becomes ``delayed``."""
    try:
        return await _resolve(probe, lag_seconds)
    except Exception:
        return AnalyticsInfo(state="delayed", reason="the analytics backend state is unavailable")


async def _resolve(probe: AnalyticsProbe, lag_seconds: float | None) -> AnalyticsInfo:
    adapter = probe.adapter
    if adapter is None:
        return AnalyticsInfo(state="disabled", reason="no analytics backend is enabled")
    reason = _matrix_reason(adapter, probe.region)
    if reason is not None:
        return AnalyticsInfo(state="disabled", reason=reason)
    health = probe.health or getattr(adapter, "health", None)
    if callable(health):
        try:
            healthy = await _probe_health(health)
        except Exception:
            return AnalyticsInfo(state="delayed", reason="the analytics backend is not responding")
        if healthy is False:
            return AnalyticsInfo(state="disabled", reason="the analytics backend is stopped")
    if lag_seconds is None:
        return AnalyticsInfo(state="delayed", reason="no aggregate has been applied yet")
    if lag_seconds > LAG_DELAYED_SECONDS:
        return AnalyticsInfo(state="delayed", reason="aggregates are behind the source data")
    return AnalyticsInfo(state="available", reason=None)
