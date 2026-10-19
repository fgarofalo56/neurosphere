"""FastAPI providers for the recommendations API (PRP-15 item 4).

* :func:`get_recommendation_store` -- ``app.state.recommendation_store`` (a
  ``RecommendationStore``); fails closed with 503 when unset.
* :func:`get_review_router` -- ``app.state.review_router`` (a ``ReviewRouter``); 503 when unset.

Tests use ``app.dependency_overrides``. No ``from __future__ import annotations``: FastAPI
inspects these signatures.
"""

from fastapi import Request
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.recommendations import RecommendationStore

from neurosphere_api.recommendations.review import ReviewRouter

__all__ = ["get_recommendation_store", "get_review_router"]


def get_recommendation_store(request: Request) -> RecommendationStore:
    store = getattr(request.app.state, "recommendation_store", None)
    if not isinstance(store, RecommendationStore):
        raise DependencyTransientError(
            "recommendation store is not configured", reason="recommendations_unconfigured"
        )
    return store


def get_review_router(request: Request) -> ReviewRouter:
    review = getattr(request.app.state, "review_router", None)
    if not isinstance(review, ReviewRouter):
        raise DependencyTransientError(
            "review router is not configured", reason="review_router_unconfigured"
        )
    return review
