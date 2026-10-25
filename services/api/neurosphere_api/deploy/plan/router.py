"""Thin HTTP handler for the deployment planner. Logic lives in :mod:`planner`.

``POST /api/v1/deploy/plan`` (deprecated alias ``/v1/deploy/plan``) is gated by
``config.manage``. The scan result is passed in the request body (a plan is a pure function of
its inputs); the planner makes no ARM or HTTP call.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from neurosphere_core.auth.scope import Permission
from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.deploy.plan.models import PlanRequest, PlanResponse
from neurosphere_api.deploy.plan.planner import build_plan, to_manifest
from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.routers import RouterRegistry

ROUTE_PREFIX = "/api/v1/deploy/plan"
#: Deprecated alias for one release (PRP-29 item 4): same router, same permissions.
ALIAS_PREFIX = "/v1/deploy/plan"


def build_router(matrix: CapabilityMatrix | None = None) -> APIRouter:
    """``matrix`` defaults to the shipped capability matrix."""
    router = APIRouter(tags=["deploy"])

    @router.post("", response_model=PlanResponse)
    async def plan(
        body: PlanRequest,
        scope: Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))],
    ) -> PlanResponse:
        built = build_plan(body, matrix=matrix)
        return PlanResponse(plan=built, manifest=to_manifest(built))

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    register_with_alias(registry, build_router(), prefix=ROUTE_PREFIX, alias_prefix=ALIAS_PREFIX)
