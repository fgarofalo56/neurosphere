"""Thin HTTP handler for the deployment planner. Logic lives in :mod:`planner`.

``POST /api/v1/deploy/plan`` (deprecated alias ``/v1/deploy/plan``) is gated by
``config.manage``. The scan input is a server-side ``scan_id`` issued to the same caller by the
scan service (preferred), or a scan result in the request body (validated fallback). The planner
itself makes no ARM or HTTP call. Scan-id misuse fails closed: another caller's id is
``forbidden``, an unknown or expired id is a typed ``invalid_schema`` (``scan_not_found`` /
``scan_expired``). Every plan, and every consent decision it evaluates, is audited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import Permission
from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, NeuroSphereError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.deploy.plan.models import PlanRequest, PlanResponse
from neurosphere_api.deploy.plan.planner import build_plan, to_manifest
from neurosphere_api.deploy.scan import ScanResponse, ScanService
from neurosphere_api.deploy.scan.audit import ENTITY_PLAN, OP_PLAN, DeployAuditor
from neurosphere_api.deploy.scan.router import auditor_for
from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.routers import RouterRegistry

ROUTE_PREFIX = "/api/v1/deploy/plan"
#: Deprecated alias for one release (PRP-29 item 4): same router, same permissions.
ALIAS_PREFIX = "/v1/deploy/plan"


def validate_body_scan(scan: ScanResponse) -> None:
    """The body fallback must be internally consistent: resources only under visible entries,
    each resource under its own subscription, no duplicate subscription entries."""
    seen: set[str] = set()
    for entry in scan.subscriptions:
        if entry.subscription_id in seen:
            raise InvalidSchemaError("duplicate subscription in scan", reason="scan_inconsistent")
        seen.add(entry.subscription_id)
        if entry.status != "visible" and entry.resources:
            raise InvalidSchemaError(
                "a not_visible subscription cannot carry resources", reason="scan_inconsistent"
            )
        if any(r.subscription_id != entry.subscription_id for r in entry.resources):
            raise InvalidSchemaError(
                "resource listed under another subscription", reason="scan_inconsistent"
            )


def _resolve_scan(
    body: PlanRequest, request: Request, scope: IdentityScope
) -> tuple[ScanResponse | None, str]:
    if body.scan_id is not None:
        service = getattr(request.app.state, "scan_service", None)
        if not isinstance(service, ScanService):
            raise DependencyTransientError("Scan is not configured.", reason="scan_not_configured")
        return service.stored_scan(scope, body.scan_id), "store"
    if body.scan is not None:
        validate_body_scan(body.scan)
        return body.scan, "body"
    return None, "none"


async def _audited_plan(
    body: PlanRequest,
    request: Request,
    scope: IdentityScope,
    auditor: DeployAuditor,
    matrix: CapabilityMatrix | None,
) -> PlanResponse:
    scan, source = _resolve_scan(body, request, scope)
    effective = body.model_copy(update={"scan": scan, "scan_id": None})
    built = build_plan(effective, matrix=matrix)
    relied = {c.consent_id for c in built.consents}
    for consent in body.consents:
        await auditor.consent_decision(
            consent.consent_id,
            granted=consent.granted,
            state={
                "resources": sorted(consent.resource_ids),
                "relied_on": consent.consent_id in relied,
            },
            operation="deploy.plan.consent",
        )
    await auditor.plan_built(
        built.plan_id,
        {
            "deployment": built.deployment_id,
            "items": [(i.service, i.status) for i in built.items],
            "scan_id": body.scan_id,
        },
        source=source,
    )
    return PlanResponse(plan=built, manifest=to_manifest(built))


def build_router(matrix: CapabilityMatrix | None = None) -> APIRouter:
    """``matrix`` defaults to the shipped capability matrix."""
    router = APIRouter(tags=["deploy"])

    @router.post("", response_model=PlanResponse)
    async def plan(
        body: PlanRequest,
        request: Request,
        scope: Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))],
    ) -> PlanResponse:
        auditor = auditor_for(request, scope)  # fails closed when audit is not configured
        try:
            return await _audited_plan(body, request, scope, auditor, matrix)
        except NeuroSphereError as exc:
            if exc.code in ("forbidden", "invalid_schema"):
                await auditor.refused(OP_PLAN, exc, target=None, entity=ENTITY_PLAN)
            raise

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    register_with_alias(registry, build_router(), prefix=ROUTE_PREFIX, alias_prefix=ALIAS_PREFIX)
