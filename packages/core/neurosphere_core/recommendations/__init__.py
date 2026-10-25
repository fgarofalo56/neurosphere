"""Recommendation store (PRP-15 item 4): scope-filtered list, get and bounded text search.

Import ``CosmosRecommendationStore`` from ``neurosphere_core.recommendations.cosmos_store`` (it
pulls in the Azure SDK, so it is not re-exported here).
"""

from neurosphere_core.recommendations.store import (
    MAX_QUERY_LENGTH,
    InMemoryRecommendationStore,
    RecommendationStore,
)

__all__ = ["MAX_QUERY_LENGTH", "InMemoryRecommendationStore", "RecommendationStore"]
