"""Budget routes, mounted at ``/api/v1/admin/platform/budgets`` (PRP-44).

| Method | Path             | Notes                                       |
|--------|------------------|---------------------------------------------|
| POST   | ``""``           | create (201, ``ETag``)                      |
| GET    | ``""``           | list, ``include_retired``                   |
| GET    | ``/{budget_id}`` | read (``ETag``)                             |
| PUT    | ``/{budget_id}`` | replace, ``If-Match`` required              |
| DELETE | ``/{budget_id}`` | retire (the record is kept), ``If-Match``   |

Stored only: nothing evaluates a budget against spend or sends an alert.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response, status
from neurosphere_contracts.admin.v1.budget import SpendBudget
from neurosphere_core.errors import NotFoundError

from neurosphere_api.admin.platform.deps import IfMatch, Platform, correlation, set_etag
from neurosphere_api.admin.platform.models import (
    MAX_PAGE_LIMIT,
    BudgetPage,
    BudgetView,
    budget_view,
)

BudgetPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-platform-budgets"])

    @router.post("", response_model=BudgetView, status_code=status.HTTP_201_CREATED)
    async def create_budget(
        request: Request, response: Response, body: SpendBudget, platform: Platform
    ) -> BudgetView:
        document = await platform.audit.run(
            correlation(request),
            "budget.put",
            "budget",
            body.budget_id.root,
            lambda: platform.admin.budgets.create(
                platform.customer_id, body, updated_by=platform.actor
            ),
            info=lambda d: (d.etag.root, {"version": d.version.root}),
        )
        set_etag(response, document.etag.root)
        return budget_view(document)

    @router.get("", response_model=BudgetPage)
    async def list_budgets(
        platform: Platform,
        include_retired: bool = False,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = 50,
    ) -> BudgetPage:
        documents = await platform.admin.budgets.list(
            platform.customer_id, include_retired=include_retired, limit=limit
        )
        return BudgetPage(items=[budget_view(d) for d in documents])

    @router.get("/{budget_id}", response_model=BudgetView)
    async def get_budget(
        response: Response, budget_id: BudgetPath, platform: Platform
    ) -> BudgetView:
        document = await platform.admin.budgets.get(platform.customer_id, budget_id)
        if document is None:
            raise NotFoundError("no such budget", reason="budget_not_found")
        set_etag(response, document.etag.root)
        return budget_view(document)

    @router.put("/{budget_id}", response_model=BudgetView)
    async def replace_budget(
        request: Request,
        response: Response,
        budget_id: BudgetPath,
        body: SpendBudget,
        if_match: IfMatch,
        platform: Platform,
    ) -> BudgetView:
        document = await platform.audit.run(
            correlation(request),
            "budget.put",
            "budget",
            budget_id,
            lambda: platform.admin.budgets.replace(
                platform.customer_id,
                budget_id,
                body,
                if_match=if_match,
                updated_by=platform.actor,
            ),
            info=lambda d: (d.etag.root, {"version": d.version.root}),
        )
        set_etag(response, document.etag.root)
        return budget_view(document)

    @router.delete("/{budget_id}", response_model=BudgetView)
    async def delete_budget(
        request: Request,
        response: Response,
        budget_id: BudgetPath,
        if_match: IfMatch,
        platform: Platform,
    ) -> BudgetView:
        document = await platform.audit.run(
            correlation(request),
            "budget.delete",
            "budget",
            budget_id,
            lambda: platform.admin.budgets.retire(
                platform.customer_id, budget_id, if_match=if_match, updated_by=platform.actor
            ),
            info=lambda d: (d.etag.root, {"version": d.version.root}),
        )
        set_etag(response, document.etag.root)
        return budget_view(document)

    return router
