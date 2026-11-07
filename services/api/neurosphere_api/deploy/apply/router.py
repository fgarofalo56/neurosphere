"""Plan approval, apply and uninstall-preview routes (PRP-08 item 12), at ``/api/v1/deploy/apply``.

| Method | Path                                        | Permission      |
|--------|---------------------------------------------|-----------------|
| POST   | ``/domains/{domain}/plans/approve``         | ``config.manage`` |
| POST   | ``/domains/{domain}/plans/apply``           | ``config.manage`` |
| POST   | ``/domains/{domain}/uninstall/preview``     | ``config.manage`` |

These routes do not change Azure. Apply and uninstall preview DRAFT an intent in the durable
action plane (``deploy_plan_apply`` / ``deploy_uninstall`` with ``dry_run=True``); validation,
confirmation, maker-checker approval and execution then run through the one action API and the
executor worker, which re-checks the approval, the plan hash, the capability matrix and the
maker's permission at execution time. There is no delete path in this module: it imports no
deleter and the uninstall body cannot clear ``dry_run``.

The ``{domain}`` path parameter is the authorization target (``config.manage`` on that domain);
``customer_id`` and the maker never come from the body. Unconfigured collaborators fail closed
with 503 (``apply_not_configured``).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, FastAPI, Path, Request, status
from neurosphere_connector.write import WriteConnector, WriteRequest
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.deploy.register import CustomerScopedRegister, LiveInventory, RegisterStore
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.actions.deploy import (
    APPLY_KIND,
    UNINSTALL_KIND,
    apply_diff,
    deployment_target,
    plan_target,
    register_digest,
    uninstall_diff,
    uninstall_preview,
)

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import DraftIntentBody
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.deploy.apply.approvals import ApprovalRecord, PlanApprovalStore
from neurosphere_api.deploy.apply.audit import (
    ENTITY_DEPLOYMENT,
    ENTITY_PLAN,
    OP_APPLY,
    OP_APPROVE,
    OP_UNINSTALL,
    ApplyAuditor,
)
from neurosphere_api.deploy.apply.models import (
    ApplyBody,
    ApplyView,
    ApprovedPlanView,
    ApprovePlanBody,
    PlannedResource,
    UninstallEntry,
    UninstallPreviewBody,
    UninstallPreviewView,
)
from neurosphere_api.deploy.scan.audit import correlation_for, opaque_id
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["ROUTE_PREFIX", "build_router", "configure_apply", "register"]

ROUTE_PREFIX: Final = "/api/v1/deploy/apply"
_UNCONFIGURED: Final = "apply_not_configured"

DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
ManageScope = Annotated[
    IdentityScope, Depends(require(Permission.CONFIG_MANAGE, domain_from_path("domain")))
]
Plane = Annotated[ActionPlane, Depends(get_action_plane)]


def configure_apply(
    app: FastAPI,
    *,
    approvals: PlanApprovalStore,
    register: RegisterStore,
    inventory: LiveInventory | None = None,
) -> None:
    """Install the collaborators on ``app.state`` (``inventory`` enables ``verify_live``)."""
    app.state.deploy_plan_approvals = approvals
    app.state.deploy_register_store = register
    app.state.deploy_live_inventory = inventory


def _approvals(request: Request) -> PlanApprovalStore:
    store = getattr(request.app.state, "deploy_plan_approvals", None)
    if not isinstance(store, PlanApprovalStore):
        raise DependencyTransientError("Apply is not configured.", reason=_UNCONFIGURED)
    return store


def _register(request: Request, scope: IdentityScope) -> RegisterStore:
    """The register as the caller's customer sees it: other customers' rows, and rows that
    carry no customer, do not exist (no existence leak)."""
    store = getattr(request.app.state, "deploy_register_store", None)
    if store is None or not callable(getattr(store, "list_rows", None)):
        raise DependencyTransientError("Apply is not configured.", reason=_UNCONFIGURED)
    return CustomerScopedRegister(store, scope.customer_id)


def _auditor(request: Request, scope: IdentityScope) -> ApplyAuditor:
    repository = getattr(request.app.state, "audit_repository", None)
    return ApplyAuditor(
        repository if isinstance(repository, AuditRepository) else None,
        scope,
        correlation_id=correlation_for(correlation_id_of(request.scope)),
    )


def _resources(record: ApprovalRecord) -> list[PlannedResource]:
    return [
        PlannedResource(
            service=r.service,
            kind=r.kind,
            disposition=r.disposition,
            name=r.name,
            region=r.region,
            sku=r.sku,
            resource_id=r.resource_id,
        )
        for r in record.resources
    ]


def _connector(plane: ActionPlane, kind: str) -> WriteConnector:
    connector = plane.connector_for(kind)
    if connector is None:
        raise CapabilityUnavailableError(
            "write_connector_unsupported_target",
            "no write connector is registered for this deploy action",
        )
    return connector


def _entry(entry: object) -> UninstallEntry:
    return UninstallEntry.model_validate(entry, from_attributes=True)


def build_router() -> APIRouter:
    router = APIRouter(tags=["deploy"])

    @router.post(
        "/domains/{domain}/plans/approve",
        response_model=ApprovedPlanView,
        status_code=status.HTTP_201_CREATED,
    )
    async def approve_plan(
        domain: DomainPath, body: ApprovePlanBody, request: Request, scope: ManageScope
    ) -> ApprovedPlanView:
        auditor = _auditor(request, scope)  # fails closed when audit is not configured
        store = _approvals(request)
        try:
            record = store.approve(scope, body.plan, body.target)
        except NeuroSphereError as exc:
            await auditor.refused_for(
                OP_APPROVE, exc, kind="plan", ident=body.plan.plan_id, entity=ENTITY_PLAN
            )
            raise
        await auditor.plan_approved(
            record.approved.plan_id,
            {
                "plan_hash": record.approved.plan_hash,
                "resources_digest": record.approved.resources_digest,
                "resources": len(record.resources),
                "domain": opaque_id("d", domain),
            },
        )
        return ApprovedPlanView(
            plan_id=record.approved.plan_id,
            plan_hash=record.approved.plan_hash,
            resources_digest=record.approved.resources_digest,
            deployment_id=record.approved.deployment_id,
            cloud=body.plan.profile.cloud,
            resources=_resources(record),
            approved_at=record.approved_at,
            expires_at=record.expires_at,
        )

    @router.post(
        "/domains/{domain}/plans/apply",
        response_model=ApplyView,
        status_code=status.HTTP_201_CREATED,
    )
    async def apply_plan(
        domain: DomainPath,
        body: ApplyBody,
        request: Request,
        scope: ManageScope,
        plane: Plane,
    ) -> ApplyView:
        auditor = _auditor(request, scope)
        try:
            record = _approvals(request).record(scope, body.plan_id)
            if body.plan_hash != record.approved.plan_hash:
                raise InvalidSchemaError(
                    "the plan changed since it was approved", reason="plan_hash_mismatch"
                )
            plan = DeployActionPlan(
                schema_version="1.0.0",
                plan_id=record.approved.plan_id,
                plan_hash=record.approved.plan_hash,
                deployment_id=record.approved.deployment_id,
                cloud=record.cloud,  # type: ignore[arg-type]
                resources=list(record.resources),
            )
            target = plan_target(record.cloud, scope.customer_id, plan.plan_id)
            planned = await _connector(plane, APPLY_KIND).dry_run(
                WriteRequest(
                    target=target, target_version=plan.plan_hash, proposed_diff=apply_diff(plan)
                )
            )
            draft = DraftIntentBody(
                action_kind=APPLY_KIND,
                target=target,
                target_version=plan.plan_hash,
                proposed_diff=planned.planned_diff,
                idempotency_key=body.idempotency_key,
                channel=body.channel,
            )
            view, _created = await ActionApi(plane).draft(
                scope, domain, draft, audit_correlation_id(correlation_id_of(request.scope))
            )
        except NeuroSphereError as exc:
            await auditor.refused_for(
                OP_APPLY, exc, kind="plan", ident=body.plan_id, entity=ENTITY_PLAN
            )
            raise
        await auditor.apply_requested(
            plan.plan_id,
            {
                "plan_hash": plan.plan_hash,
                "intent": view.intent.intent_id.root,
                "resources": len(plan.resources),
            },
        )
        return ApplyView(
            plan_id=plan.plan_id,
            plan_hash=plan.plan_hash,
            resources=_resources(record),
            action=view,
        )

    @router.post(
        "/domains/{domain}/uninstall/preview",
        response_model=UninstallPreviewView,
        status_code=status.HTTP_201_CREATED,
    )
    async def preview_uninstall(
        domain: DomainPath,
        body: UninstallPreviewBody,
        request: Request,
        scope: ManageScope,
        plane: Plane,
    ) -> UninstallPreviewView:
        auditor = _auditor(request, scope)
        try:
            rows = await _register(request, scope).list_rows(body.deployment_id)
            if not rows:
                raise InvalidSchemaError(
                    "no register rows for this deployment", reason="deployment_not_found"
                )
            inventory = None
            if body.verify_live:
                inventory = getattr(request.app.state, "deploy_live_inventory", None)
                if inventory is None:
                    raise CapabilityUnavailableError(
                        "live_inventory_not_configured",
                        "live resource group verification is not configured",
                    )
            removal = await uninstall_preview(body.deployment_id, rows, inventory)
            digest = register_digest(rows)
            removable = [e.resource_id for e in removal.removable]
            target = deployment_target(scope.cloud, scope.customer_id, body.deployment_id)
            diff = uninstall_diff(digest, removable)
            await _connector(plane, UNINSTALL_KIND).dry_run(
                WriteRequest(target=target, target_version=digest, proposed_diff=diff)
            )
            draft = DraftIntentBody(
                action_kind=UNINSTALL_KIND,
                target=target,
                target_version=digest,
                proposed_diff=diff,
                idempotency_key=body.idempotency_key,
                channel=body.channel,
                dry_run=True,
            )
            view, _created = await ActionApi(plane).draft(
                scope, domain, draft, audit_correlation_id(correlation_id_of(request.scope))
            )
        except NeuroSphereError as exc:
            await auditor.refused_for(
                OP_UNINSTALL,
                exc,
                kind="deployment",
                ident=body.deployment_id,
                entity=ENTITY_DEPLOYMENT,
            )
            raise
        await auditor.uninstall_previewed(
            body.deployment_id,
            {
                "register_digest": digest,
                "removable": len(removable),
                "untouched": len(removal.entries) - len(removable),
                "live_verified": body.verify_live,
            },
        )
        removable_set = {e.resource_id for e in removal.removable}
        return UninstallPreviewView(
            deployment_id=body.deployment_id,
            register_digest=digest,
            removable=[_entry(e) for e in removal.removable],
            untouched=[_entry(e) for e in removal.entries if e.resource_id not in removable_set],
            action=view,
        )

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    registry.register(ROUTE_PREFIX, build_router())
