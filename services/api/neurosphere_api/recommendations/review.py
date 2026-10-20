"""The ``ReviewRouter`` seam (PRP-17 interface) and its in-memory stub.

"Route to review" only creates a pending review request; nothing here, and nothing in this
package, executes a change. PRP-17 replaces the stub with the real HITL queue behind the same
protocol. The stub is idempotent: routing the same recommendation again returns the same request.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from neurosphere_core.scope import IdentityScope

__all__ = ["InMemoryReviewRouter", "ReviewRequest", "ReviewRouter"]


@dataclass(frozen=True)
class ReviewRequest:
    review_request_id: str
    state: Literal["pending_review"] = "pending_review"


@runtime_checkable
class ReviewRouter(Protocol):
    async def route(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest:
        """Create (or return the existing) pending review request for the recommendation."""
        ...

    async def status(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest | None:
        """The pending review request for the recommendation, or ``None`` when not routed."""
        ...


class InMemoryReviewRouter:
    def __init__(self) -> None:
        self._requests: dict[tuple[str, str], ReviewRequest] = {}

    async def route(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest:
        key = (scope.customer_id, recommendation_id)
        existing = self._requests.get(key)
        if existing is not None:
            return existing
        digest = hashlib.sha256(f"{scope.customer_id}|{recommendation_id}".encode()).hexdigest()
        request = ReviewRequest(review_request_id=f"rr-{digest[:24]}")
        self._requests[key] = request
        return request

    async def status(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest | None:
        return self._requests.get((scope.customer_id, recommendation_id))
