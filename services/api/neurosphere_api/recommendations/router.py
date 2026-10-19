"""Recommendations route (PRP-15 item 4), mounted at ``/api/v1/recommendations``.

| Method | Path                                                    | Permission       |
|--------|---------------------------------------------------------|------------------|
| GET    | ``/domains/{domain}``                                   | ``data.read``      |
| GET    | ``/domains/{domain}/items/{recommendation_id:path}``    | ``data.read``      |
| POST   | ``/domains/{domain}/review-requests``                   | ``action.propose`` |
| POST   | ``/domains/{domain}/executions``                        | ``action.propose`` |

Recommendations are advisory. Nothing here executes a change: ``review-requests`` only creates a
pending review request through the ``ReviewRouter`` seam (PRP-17), and ``executions`` always
refuses with ``capability_unavailable`` ("action gates not passed"). The path ``{domain}`` is the
addressed resource and the authorization TARGET, checked against the derived ``IdentityScope``
(403 outside it, 503 on a policy-store outage). ``customer_id`` and ``domain_id`` never come from
the query or body.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.recommendations import MAX_QUERY_LENGTH, RecommendationStore
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.recommendations.dependencies import (
    get_recommendation_store,
    get_review_router,
)
from neurosphere_api.recommendations.models import (
    EXECUTION_REFUSAL_REASON,
    EXECUTION_REFUSAL_REASON_CODE,
    ExecutionState,
    RecommendationDetail,
    RecommendationList,
    ReviewRequestBody,
    ReviewRequestCreated,
    ReviewState,
)
from neurosphere_api.recommendations.review import ReviewRouter
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/recommendations"

Kind = Literal[
    "cost_spike",
    "latency_degradation",
    "error_rate_degradation",
    "unused_agent",
    "candidate_duplicate",
    "model_right_sizing",
]

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
ProposeScope = Annotated[
    IdentityScope, Depends(require(Permission.ACTION_PROPOSE, domain_from_path("domain")))
]
Store = Annotated[RecommendationStore, Depends(get_recommendation_store)]
Review = Annotated[ReviewRouter, Depends(get_review_router)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
IdPath = Annotated[str, Path(min_length=1, max_length=512)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="recommendation not found")


def build_router() -> APIRouter:
    router = APIRouter(tags=["recommendations"])

    @router.get(
        "/domains/{domain}", response_model=RecommendationList, response_model_exclude_unset=True
    )
    async def list_recommendations(
        domain: DomainPath,
        scope: ReadScope,
        store: Store,
        kind: Annotated[Kind | None, Query()] = None,
        q: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> RecommendationList:
        page = await store.list(scope, domain, kind=kind, q=q, cursor=cursor, limit=limit)
        return RecommendationList(items=list(page.items), next_cursor=page.next_cursor)

    @router.get(
        "/domains/{domain}/items/{recommendation_id:path}",
        response_model=RecommendationDetail,
        response_model_exclude_unset=True,
    )
    async def get_recommendation(
        domain: DomainPath,
        recommendation_id: IdPath,
        scope: ReadScope,
        store: Store,
        review: Review,
    ) -> RecommendationDetail:
        rec = await store.get(scope, domain, recommendation_id)
        if rec is None:
            raise _not_found()
        pending = await review.status(scope, domain, recommendation_id)
        state = (
            ReviewState(state="not_routed", review_request_id=None)
            if pending is None
            else ReviewState(state=pending.state, review_request_id=pending.review_request_id)
        )
        return RecommendationDetail(
            recommendation=rec,
            review=state,
            execution=ExecutionState(executable=False, reason=EXECUTION_REFUSAL_REASON),
        )

    @router.post(
        "/domains/{domain}/review-requests",
        status_code=202,
        response_model=ReviewRequestCreated,
    )
    async def create_review_request(
        domain: DomainPath,
        body: ReviewRequestBody,
        scope: ProposeScope,
        store: Store,
        review: Review,
    ) -> ReviewRequestCreated:
        rec = await store.get(scope, domain, body.recommendation_id)
        if rec is None:
            raise _not_found()
        created = await review.route(scope, domain, body.recommendation_id)
        return ReviewRequestCreated(
            review_request_id=created.review_request_id, state=created.state
        )

    @router.post("/domains/{domain}/executions", status_code=409)
    async def refuse_execution(domain: DomainPath, scope: ProposeScope) -> None:
        # Authn/authz ran first (401/403). There is deliberately no executing code path.
        raise CapabilityUnavailableError(
            EXECUTION_REFUSAL_REASON_CODE, detail=EXECUTION_REFUSAL_REASON
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
