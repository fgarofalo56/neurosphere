"""Capability gating and the fixture fallback for Azure-backed search.

Ranking tolerance (fixture vs Azure), used by the comparison tests and by anyone validating a
live index against the fixture: for the same scope and request the two must return the **same
set of IDs** (and the same ``matched`` count when no budget cut applies). **Order may differ**:
the fixture scores with in-scope BM25 and Azure with its own BM25 over the whole index, so
scores are not comparable and ties (equal score) may order differently. Scores are never
compared across implementations.

Gating: Azure search is used only when the capability matrix says ``ai_search.base`` is
supported for the deployment cloud and region and a backend is configured for that same
cloud. Otherwise the in-process fixture answers. A Government deployment without a verified
row is disabled with its reason and is never routed to a Commercial endpoint.
"""

from __future__ import annotations

from datetime import date

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope

from neurosphere_core.capabilities import (
    CapabilityMatrix,
    CapabilityResult,
    DeploymentProfile,
    FeatureRequest,
    validate_profile,
)
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.search.azure.client import AzureAuthorizedSearch
from neurosphere_core.search.protocol import AuthorizedSearch, SearchRequest, SearchResult

__all__ = ["FallbackAuthorizedSearch", "azure_search_capability", "require_azure_search"]


def azure_search_capability(
    cloud: str,
    region: str,
    *,
    matrix: CapabilityMatrix | None = None,
    today: date | None = None,
) -> CapabilityResult:
    """Resolve ``ai_search.base`` for one cloud and region (same-cloud rows only)."""
    profile = DeploymentProfile.model_validate(
        {
            "cloud": cloud,
            "regions": (region,),
            "hosting": "aks",
            "analytics": "fabric",
            "features": (FeatureRequest(service="ai_search", feature="base"),),
        }
    )
    result = validate_profile(profile, matrix, today)
    return next(r for r in result.results if r.kind == "feature")


def require_azure_search(capability: CapabilityResult) -> None:
    """Raise ``CapabilityUnavailableError`` (with the matrix reason) when disabled."""
    if capability.status != "supported":
        raise CapabilityUnavailableError(
            capability.reason_code or "not_verified", capability.reason
        )


class FallbackAuthorizedSearch:
    """Azure search when enabled and configured for the scope's cloud, else the fixture."""

    def __init__(
        self,
        fallback: AuthorizedSearch,
        *,
        azure: AzureAuthorizedSearch | None = None,
        capability: CapabilityResult | None = None,
    ) -> None:
        self._fallback = fallback
        self._azure = azure
        self._capability = capability

    @property
    def azure_enabled(self) -> bool:
        """True when a backend is configured and the capability row is supported."""
        return (
            self._azure is not None
            and self._capability is not None
            and self._capability.status == "supported"
        )

    @property
    def disabled_reason(self) -> str | None:
        if self._azure is None:
            return "azure search is not configured"
        if self._capability is None:
            return "azure search capability has not been verified"
        return self._capability.reason if self._capability.status != "supported" else None

    async def search(self, scope: IdentityScope, request: SearchRequest) -> SearchResult:
        azure = self._azure
        if azure is not None and self.azure_enabled and azure.cloud == scope.cloud:
            return await azure.search(scope, request)
        return await self._fallback.search(scope, request)
