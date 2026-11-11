"""Evaluation quality routes (PRP-16 item 4), mounted at ``/api/v1/evaluation``.

| Method | Path                              | Permission  |
|--------|-----------------------------------|-------------|
| GET    | ``/domains/{domain}/results``     | ``data.read`` |
| GET    | ``/domains/{domain}/quality``     | ``data.read`` |
| GET    | ``/domains/{domain}/calibration-samples?subject_ref=`` | ``data.read`` |

The path ``{domain}`` is the addressed resource and the authorization TARGET, checked against the
derived ``IdentityScope`` (403 outside it, 503 on a policy-store outage). ``customer_id`` and
``domain_id`` never come from the query. Read-only: nothing here acts on a judge score.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.evaluation.store import EvaluationStore
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.evaluation.dependencies import (
    get_evaluation_store,
    get_pilot_dataset_ids,
    get_quality_window,
)
from neurosphere_api.evaluation.models import (
    CalibrationSampleOut,
    QualityResponse,
    ResultsList,
    Truncation,
)
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
QualityWindow = Annotated[tuple[datetime, int, int], Depends(get_quality_window)]
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
        window: QualityWindow,
        subject_id: SubjectQuery = None,
    ) -> QualityResponse:
        since, window_days, max_results = window
        windowed = await store.results_window(
            scope, domain, subject_id=subject_id, since=since, limit=max_results
        )
        response = compute_quality(
            windowed.items,
            await store.calibrations(scope, domain),
            await store.coverage(scope, domain),
            await store.drift_alerts(scope, domain, subject_id=subject_id),
            pilot_dataset_ids,
        )
        if windowed.truncated:
            response.truncated = Truncation(limit=max_results, window_days=window_days)
        return response

    @router.get("/domains/{domain}/calibration-samples", response_model=CalibrationSampleOut)
    async def calibration_sample(
        domain: DomainPath,
        scope: ReadScope,
        store: Store,
        subject_ref: Annotated[str, Query(min_length=1, max_length=512)],
    ) -> CalibrationSampleOut:
        sample = await store.get_calibration_sample(scope, domain, subject_ref)
        if sample is None:
            raise HTTPException(status_code=404, detail="calibration sample not found")
        return CalibrationSampleOut(
            subject_ref=sample.subject_ref,
            domain_id=sample.domain_id,
            dataset_id=sample.dataset_id,
            dataset_version=sample.dataset_version,
            item_id=sample.item_id,
            dimension=sample.dimension,
            classification=sample.classification,
            judge_config_id=sample.judge_config_id,
            judge_config_version=sample.judge_config_version,
            value=sample.value,
            rubric_id=sample.rubric_id,
            rubric_version=sample.rubric_version,
            opened_at=sample.opened_at.isoformat(),
            payload=sample.payload,
            payload_withheld=sample.payload_withheld,
            withheld_reason=sample.withheld_reason,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
