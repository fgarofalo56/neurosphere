"""The two analytics capability contracts (PRP-11, ADR-0007).

Both take a closed, typed request and a REQUIRED keyword-only ``scope``: the server-derived
``IdentityScope`` (never a request field). Implementations must apply the scope's
``customer_id``, ``allowed_domains`` and ``cloud`` as mandatory predicates before aggregating,
treat caller filters as narrowing only, refuse a scope whose cloud differs from their own
(``forbidden``, reason ``cloud_mismatch``), enforce the request budget and raise
``rate_limited`` on a breach. No method accepts query text.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_core.analytics.base.models import (
    AggregateRequest,
    AggregateResult,
    Cloud,
    CoUsageRequest,
    CoUsageResult,
)
from neurosphere_core.scope import IdentityScope


@runtime_checkable
class TelemetryAnalytics(Protocol):
    backend: str
    cloud: Cloud

    async def aggregate(
        self, request: AggregateRequest, *, scope: IdentityScope
    ) -> AggregateResult: ...


@runtime_checkable
class RecommendationCompute(Protocol):
    backend: str
    cloud: Cloud

    async def co_usage_candidates(
        self, request: CoUsageRequest, *, scope: IdentityScope
    ) -> CoUsageResult:
        """Bounded co-usage job. Returns candidates only; evaluation and HITL come later."""
        ...


@runtime_checkable
class AnalyticsAdapter(TelemetryAnalytics, RecommendationCompute, Protocol):
    """What the registry hands out: both capabilities from one backend."""
