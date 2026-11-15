"""Lifecycle routes (PRP-23 item 3), mounted at ``/api/v1/lifecycle``.

Every route needs ``lifecycle.manage``:

* ``POST /holds`` (201), ``GET /holds``, ``DELETE /holds/{hold_id}`` (204)
* ``POST /requests`` (202), ``GET /requests``, ``GET /requests/{request_id}``
* ``GET /status`` (mode, policy state, queue depth)

The permission is held at the customer level (the same rule as the emergency
kill switch): these actions delete data across the whole customer. Identity, customer and cloud
come from the verified scope; a ``customer_id`` or ``domain_id`` in a body is ignored. Every
write is audited with before and after records (``run_audited_mutation``, fail closed). The API
never deletes anything: it persists a job and the worker runs it, in dry-run unless the worker is
configured with ``NS_LIFECYCLE_MODE=execute``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    build_after,
    build_before,
    build_denied,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NotFoundError,
)
from neurosphere_core.lifecycle import LegalHold
from neurosphere_core.lifecycle.engine import lifecycle_canonical_id
from neurosphere_core.lifecycle.jobs import LifecycleJob
from neurosphere_core.lifecycle.rules import is_audit_label
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.actions.customer_control import require_customer_control
from neurosphere_api.lifecycle.models import (
    HoldCreate,
    HoldView,
    RequestAccepted,
    RequestCreate,
    RequestView,
    StatusView,
)
from neurosphere_api.lifecycle.state import STATE_ATTRIBUTE, LifecycleApiState
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "get_lifecycle", "register"]

PREFIX: Final = "/api/v1/lifecycle"

Manager = Annotated[IdentityScope, Depends(require_customer_control(Permission.LIFECYCLE_MANAGE))]
HoldId = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
RequestId = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
Limit = Annotated[int, Query(ge=1, le=100)]


def get_lifecycle(request: Request) -> LifecycleApiState:
    state = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(state, LifecycleApiState):
        raise DependencyTransientError(
            "the lifecycle service is not configured", reason="lifecycle_unconfigured"
        )
    return state


Lifecycle = Annotated[LifecycleApiState, Depends(get_lifecycle)]


def _ctx(scope: IdentityScope, request: Request, operation: str) -> AuditContext:
    return AuditContext.from_scope(
        scope,
        correlation_id=audit_correlation_id(correlation_id_of(request.scope)),
        operation=operation,
        channel="rest",
    )


def _subject(scope: IdentityScope, entity: str, ident: str, state: dict[str, object]):
    canonical = lifecycle_canonical_id(str(scope.cloud), scope.customer_id, entity, ident, entity)
    return make_subject(canonical, entity, state=state)


def _view(job: LifecycleJob) -> RequestView:
    return RequestView(
        request_id=job.job_id,
        action=job.request.action,
        state=job.state.value,
        dry_run=job.dry_run,
        requested_by=job.requested_by,
        submitted_at=job.submitted_at,
        updated_at=job.updated_at,
        outcome=job.outcome,
    )


def build_router() -> APIRouter:
    router = APIRouter(tags=["lifecycle"])

    # -- holds ---------------------------------------------------------------------------------

    @router.post("/holds", response_model=HoldView, status_code=201)
    async def place_hold(
        body: HoldCreate, request: Request, scope: Manager, lifecycle: Lifecycle
    ) -> HoldView:
        ctx = _ctx(scope, request, "lifecycle.hold.place")
        hold = LegalHold.model_validate(
            {**body.model_dump(), "placed_at": lifecycle.clock()}  # a selector is required
        )
        selectors = {
            k: v for k, v in body.model_dump().items() if k != "custodians" and v is not None
        }
        subject = _subject(scope, "legal_hold", hold.hold_id, {**selectors, "state": "placed"})

        async def mutate() -> bool:
            await lifecycle.holds.place(hold)
            return any(h.hold_id == hold.hold_id for h in await lifecycle.holds.active())

        def after(verified: bool) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="succeeded" if verified else "failed",
                verified=verified,
                detail="hold_placed" if verified else "readback_missing",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="failed",
                verified=False,
                detail=getattr(exc, "reason", None) or "action_error",
            )

        verified = await run_audited_mutation(
            lifecycle.audit,
            lifecycle.chain_id(scope.customer_id),
            before=build_before(ctx, subject),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
        if not verified:
            raise DependencyTransientError(
                "the hold could not be read back", reason="hold_unverified"
            )
        return HoldView.of(hold)

    @router.get("/holds", response_model=list[HoldView])
    async def list_holds(scope: Manager, lifecycle: Lifecycle) -> list[HoldView]:
        holds = await lifecycle.holds.active()
        return [HoldView.of(h) for h in sorted(holds, key=lambda h: (h.placed_at, h.hold_id))]

    @router.delete("/holds/{hold_id}", status_code=204)
    async def release_hold(
        hold_id: HoldId, request: Request, scope: Manager, lifecycle: Lifecycle
    ) -> Response:
        ctx = _ctx(scope, request, "lifecycle.hold.release")
        if all(h.hold_id != hold_id for h in await lifecycle.holds.active()):
            raise NotFoundError("no such legal hold", reason="hold_not_found")
        subject = _subject(scope, "legal_hold", hold_id, {"state": "released"})

        async def mutate() -> bool:
            released = await lifecycle.holds.release(hold_id)
            return released and all(h.hold_id != hold_id for h in await lifecycle.holds.active())

        def after(verified: bool) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="succeeded" if verified else "failed",
                verified=verified,
                detail="hold_released" if verified else "readback_found_hold",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="failed",
                verified=False,
                detail=getattr(exc, "reason", None) or "action_error",
            )

        verified = await run_audited_mutation(
            lifecycle.audit,
            lifecycle.chain_id(scope.customer_id),
            before=build_before(ctx, subject),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
        if not verified:
            raise DependencyTransientError(
                "the hold release could not be verified", reason="hold_release_unverified"
            )
        return Response(status_code=204)

    # -- requests ------------------------------------------------------------------------------

    @router.post("/requests", response_model=RequestAccepted, status_code=202)
    async def submit_request(
        body: RequestCreate, request: Request, scope: Manager, lifecycle: Lifecycle
    ) -> RequestAccepted:
        ctx = _ctx(scope, request, "lifecycle.request.submit")
        lifecycle_request = body.to_request()
        chain = lifecycle.chain_id(scope.customer_id)
        job = LifecycleJob(
            request=lifecycle_request,
            ctx=ctx.model_copy(update={"channel": "worker"}),
            dry_run=body.dry_run,
            requested_by=ctx.actor.principal_pseudonym,
            submitted_at=lifecycle.clock(),
        )
        subject = _subject(
            scope,
            "lifecycle_request",
            job.job_id,
            {"action": body.action.value, "dry_run": body.dry_run},
        )
        ref = lifecycle_request.target
        if ref is not None and is_audit_label(ref):
            await lifecycle.audit.append(
                chain,
                build_denied(ctx, code="forbidden", reason="audit_immutable", subject=subject),
            )
            raise ForbiddenError(
                "the audit store is never a lifecycle target", reason="audit_immutable"
            )

        async def mutate() -> tuple[LifecycleJob, bool]:
            return await lifecycle.jobs.submit(job)

        def after(result: tuple[LifecycleJob, bool]) -> AuditDraft:
            stored, created = result
            return build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail="job_persisted" if created else f"job_duplicate_of_{stored.state.value}",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="failed",
                verified=False,
                detail=getattr(exc, "reason", None) or "action_error",
            )

        stored, created = await run_audited_mutation(
            lifecycle.audit,
            chain,
            before=build_before(ctx, subject),
            mutate=mutate,
            after=after,
            on_error=failed,
        )
        return RequestAccepted(
            request_id=stored.job_id, state=stored.state.value, deduplicated=not created
        )

    @router.get("/requests", response_model=list[RequestView])
    async def list_requests(
        scope: Manager, lifecycle: Lifecycle, limit: Limit = 50
    ) -> list[RequestView]:
        return [_view(j) for j in await lifecycle.jobs.list(limit=limit)]

    @router.get("/requests/{request_id}", response_model=RequestView)
    async def get_request(
        request_id: RequestId, scope: Manager, lifecycle: Lifecycle
    ) -> RequestView:
        job = await lifecycle.jobs.get(request_id)
        if job is None:
            raise NotFoundError("no such lifecycle request", reason="request_not_found")
        return _view(job)

    # -- status --------------------------------------------------------------------------------

    @router.get("/status", response_model=StatusView)
    async def status(scope: Manager, lifecycle: Lifecycle) -> StatusView:
        return StatusView.of(
            mode=lifecycle.mode,
            policy=lifecycle.policy,
            depth=await lifecycle.jobs.depth(),
            holds=len(await lifecycle.holds.active()),
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
