"""Evaluation quality routes (PRP-16 item 4), mounted at ``/api/v1/evaluation``.

| Method | Path                              | Permission  |
|--------|-----------------------------------|-------------|
| GET    | ``/domains/{domain}/results``     | ``data.read`` |
| GET    | ``/domains/{domain}/quality``     | ``data.read`` |

The path ``{domain}`` is the addressed resource and the authorization TARGET, checked against the
derived ``IdentityScope`` (403 outside it, 503 on a policy-store outage). ``customer_id`` and
``domain_id`` never come from the query. Read-only: nothing here acts on a judge score.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.evaluation.store import EvaluationStore
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.evaluation.dependencies import get_evaluation_store, get_pilot_dataset_ids
from neurosphere_api.evaluation.models import QualityResponse, ResultsList
from neurosphere_api.evaluation.quality import compute_quality
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/evaluation"

Dimension = Literal[
    "task_success", "groundedness", "safety", "tool_correctness", "user_feedback", "drift"
]

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
Store = Annotated[EvaluationStore, Depends(get_evaluation_store)]
PilotIds = Annotated[frozenset[str], Depends(get_pilot_dataset_ids)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
SubjectQuery = Annotated[str | None, Query(min_length=1, max_length=512)]


def build_router() -> APIRouter:
    router = APIRouter(tags=["evaluation"])

    @router.get(
        "/domains/{domain}/results",
        response_model=ResultsList,
        response_model_exclude_unset=True,
    )
    async def list_results(
        domain: DomainPath,
        scope: ReadScope,
        store: Store,
        subject_id: SubjectQuery = None,
        dimension: Annotated[Dimension | None, Query()] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> ResultsList:
        page = await store.list_results(
            scope, domain, subject_id=subject_id, dimension=dimension, cursor=cursor, limit=limit
        )
        return ResultsList(items=list(page.items), next_cursor=page.next_cursor)

    @router.get("/domains/{domain}/quality", response_model=QualityResponse)
    async def quality(
        domain: DomainPath,
        scope: ReadScope,
        store: Store,
        pilot_dataset_ids: PilotIds,
        subject_id: SubjectQuery = None,
    ) -> QualityResponse:
        results = await store.results(scope, domain, subject_id=subject_id)
        return compute_quality(
            results,
            await store.calibrations(scope, domain),
            await store.coverage(scope, domain),
            await store.drift_alerts(scope, domain, subject_id=subject_id),
            pilot_dataset_ids,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
