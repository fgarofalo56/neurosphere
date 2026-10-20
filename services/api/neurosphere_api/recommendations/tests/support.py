"""Harness for recommendations API tests: the PRP-06 authz harness (dev-issuer tokens, in-memory
policy store) with the real router, an in-memory store and the in-memory review router. No network.

ALICE views FINANCE, BOB views OPERATIONS, CAROL is an analyst in FINANCE (``action.propose``).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.auth.scope import Role
from neurosphere_core.recommendations import InMemoryRecommendationStore

from neurosphere_api.recommendations import PREFIX, InMemoryReviewRouter, build_router

__all__ = [
    "ALICE",
    "BOB",
    "CAROL",
    "FINANCE",
    "OPERATIONS",
    "Api",
    "example",
    "make_api",
    "make_rec",
    "rec_from_example",
]

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CAROL: str = helpers.CAROL
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
EXAMPLES = (
    Path(__file__).resolve().parents[5]
    / "packages/contracts/schemas/recommendations/v1/examples/valid"
)


def example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def make_rec(n: int, *, domain: str = FINANCE, **overrides: Any) -> Recommendation:
    data = example("recommendation.cost-spike-scored.json")
    data["recommendation_id"] = f"commercial:contoso:neurosphere:recommendation:rec-{n:04d}"
    data["domain_id"] = domain
    data.update(overrides)
    return Recommendation.model_validate(data)


def rec_from_example(name: str, n: int = 1, *, domain: str = FINANCE) -> Recommendation:
    """A recommendation built from one contract example verbatim (id and domain re-addressed)."""
    data = example(name)
    data["recommendation_id"] = f"commercial:contoso:neurosphere:recommendation:rec-{n:04d}"
    data["domain_id"] = domain
    return Recommendation.model_validate(data)


@dataclass
class Api:
    h: Any
    store: InMemoryRecommendationStore
    review: InMemoryReviewRouter

    def get(self, who: str | None, path: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=headers)

    def post(self, who: str | None, path: str, body: Any = None) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.post(f"{PREFIX}{path}", json=body, headers=headers)


def make_api(*recs: Recommendation, wire: bool = True) -> Api:
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
        helpers.policy(CAROL, helpers.role(Role.ANALYST, FINANCE)),
        routers={PREFIX: build_router()},
    )
    store = InMemoryRecommendationStore(recs)
    review = InMemoryReviewRouter()
    if wire:
        h.app.state.recommendation_store = store
        h.app.state.review_router = review
    return Api(h=h, store=store, review=review)
