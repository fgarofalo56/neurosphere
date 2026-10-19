"""Recommendations API (PRP-15 item 4): advisory list, detail and route-to-review.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/recommendations``) for ``RouterRegistry``.
  Not added to ``routers.py`` here; PRP-15 item 6 owns that wiring.
* :func:`get_recommendation_store` -- reads ``app.state.recommendation_store`` (503 when unset).
* :func:`get_review_router` -- reads ``app.state.review_router`` (503 when unset).

Nothing in this package executes a change; the executions route only refuses.
"""

from neurosphere_api.recommendations.dependencies import (
    get_recommendation_store,
    get_review_router,
)
from neurosphere_api.recommendations.review import (
    InMemoryReviewRouter,
    ReviewRequest,
    ReviewRouter,
)
from neurosphere_api.recommendations.router import PREFIX, build_router, register

__all__ = [
    "PREFIX",
    "InMemoryReviewRouter",
    "ReviewRequest",
    "ReviewRouter",
    "build_router",
    "get_recommendation_store",
    "get_review_router",
    "register",
]
