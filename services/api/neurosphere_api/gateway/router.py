"""Gateway registry routes, mounted at ``/api/v1/gateways`` (PRP-33 item 6; PRP-34 item 2).

| Method | Path                                          | Permission      |
|--------|-----------------------------------------------|-----------------|
| POST   | ``/domains/{domain}/gateways``                | ``config.manage`` |
| GET    | ``/domains/{domain}/gateways``                | ``data.read``   |
| GET    | ``/domains/{domain}/gateways/{gateway_id}``   | ``data.read``   |
| GET    | ``/domains/{domain}/gateways/{gateway_id}/inventory`` | ``data.read`` |
| POST   | ``/domains/{domain}/gateways/{gateway_id}/sync`` | ``config.manage`` |
| POST   | ``/domains/{domain}/gateways/{gateway_id}/mode`` | ``action.propose`` |

The path ``{domain}`` is the authorization target (403 outside the caller's scope, 503 on a
policy-store outage). There is no ``deploy.*`` permission in the shipped permission set, so the
gateway write routes use ``config.manage`` (the precedent of the discovery scan and the plan
routes) and the read routes ``data.read``. No route writes to the gateway itself.

``.../mode`` (PRP-34 item 2) never flips the mode itself: it DRAFTS a ``gateway_mode_change``
action intent through the one action plane (same ``ActionApi.draft`` as ``POST
/api/v1/actions/.../intents``), so validate, confirmation, maker-checker approval and the
executor worker apply exactly as for any other action. The executor's connector step runs the
write-permission preflight and flips the registration. The route needs only ``action.propose`` on
the gateway's domain (maker-checker is unchanged: another principal approves through the normal
action flow); it refuses an
unchanged mode, manage in a Government profile (``gateway_manage_unavailable``) and a gateway
whose domain has an APIM action executing (``gateway_applying``). Every request is audited on the
``<customer>.gateway`` chain (before record, then the drafted intent or the refusal).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions.targets import APIM_GATEWAY_CONNECTOR, connector_name_for
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from neurosphere_core.gateway import GatewayInventory, GatewayMode, GatewayRegistration
from neurosphere_core.gateway.mode import (
    GATEWAY_APPLYING,
    MODE_CHANGE_KIND,
    MODE_UNCHANGED,
    manage_refusal,
    mode_change_diff,
    mode_target,
    mode_target_version,
)
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import ActionView, DraftIntentBody
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.gateway.dependencies import GatewayPlane, get_gateway_plane
from neurosphere_api.gateway.models import GatewayDetail, GatewayList, RegisterGatewayBody
from neurosphere_api.gateway.service import ENTITY_TYPE, GatewayApi, audit_chain_id
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "GatewayModeBody", "build_router", "register"]

PREFIX: Final = "/api/v1/gateways"
#: Pages of executing intents read before the busy check gives up and refuses (fail closed).
_MAX_BUSY_PAGES: Final = 20

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
WriteScope = Annotated[
    IdentityScope, Depends(require(Permission.CONFIG_MANAGE, domain_from_path("domain")))
]
# The mode route drafts an action intent, so it needs only the scoped draft permission.
ProposeScope = Annotated[
    IdentityScope, Depends(require(Permission.ACTION_PROPOSE, domain_from_path("domain")))
]
Plane = Annotated[GatewayPlane, Depends(get_gateway_plane)]
Actions = Annotated[ActionPlane, Depends(get_action_plane)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
GatewayPath = Annotated[str, Path(pattern=GATEWAY_ID_PATTERN)]


class GatewayModeBody(BaseModel):
    """``POST .../mode``: the requested mode. Identity, target and version are server-side."""

    model_config = ConfigDict(extra="forbid")

    mode: GatewayMode
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{16,128}$")]
    channel: Literal["button", "chat", "rest", "mcp"] = "rest"


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def _code(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, str) and reason else "error"


async def _apim_action_executing(actions: ActionPlane, customer_id: str, domain: str) -> bool:
    """True while an APIM gateway intent of the domain is ``executing`` (apply, canary, verify,
    rollback or unpublish in flight). Too many to read is treated as busy (fail closed)."""
    cursor: str | None = None
    for _ in range(_MAX_BUSY_PAGES):
        page = await actions.intents.list(
            customer_id, domain, state="executing", cursor=cursor, limit=MAX_PAGE_SIZE
        )
        for stored in page.items:
            intent = stored.intent
            name = connector_name_for(intent.action_kind, intent.target.entity_type)
            if name == APIM_GATEWAY_CONNECTOR:
                return True
        cursor = page.next_cursor
        if cursor is None:
            return False
    return True


async def _draft_mode_change(
    plane: GatewayPlane,
    actions: ActionPlane,
    scope: IdentityScope,
    domain: str,
    gateway_id: str,
    body: GatewayModeBody,
    correlation_id: str,
) -> tuple[ActionView, bool]:
    registration = await plane.store.get(scope.customer_id, domain, gateway_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="not found")
    ctx = AuditContext.from_scope(
        scope, correlation_id=correlation_id, operation="gateway.mode_change", channel=body.channel
    )
    subject_id = f"{scope.cloud}:{scope.customer_id}:neurosphere:{ENTITY_TYPE}:{gateway_id}"
    state = {
        "mode_from": registration.mode,
        "mode_to": body.mode,
        "mode_revision": registration.mode_revision,
    }

    async def mutate() -> tuple[ActionView, bool]:
        if body.mode == registration.mode:
            raise InvalidSchemaError(
                f"the gateway is already in {registration.mode} mode", reason=MODE_UNCHANGED
            )
        if body.mode == "manage":
            refusal = manage_refusal(registration.cloud)
            if refusal is not None:
                raise refusal
        if await _apim_action_executing(actions, scope.customer_id, domain):
            raise CapabilityUnavailableError(
                GATEWAY_APPLYING, "an APIM gateway action is executing in this domain"
            )
        draft = DraftIntentBody(
            action_kind=MODE_CHANGE_KIND,
            target=TargetRef.model_validate(mode_target(registration)),
            target_version=mode_target_version(registration),
            proposed_diff=ProposedDiff.model_validate(
                {
                    "format": "json_patch",
                    "operations": mode_change_diff(body.mode, ctx.actor.principal_pseudonym),
                }
            ),
            idempotency_key=body.idempotency_key,
            channel=body.channel,
        )
        return await ActionApi(actions).draft(scope, domain, draft, correlation_id)

    def after(result: tuple[ActionView, bool]) -> AuditDraft:
        subject = make_subject(subject_id, ENTITY_TYPE, state=state)
        return build_after(
            ctx, subject, result="succeeded", verified=False, detail=f"drafted:mode={body.mode}"
        )

    def failed(exc: BaseException) -> AuditDraft:
        subject = make_subject(subject_id, ENTITY_TYPE, state=state)
        return build_after(ctx, subject, result="failed", verified=False, detail=_code(exc))

    return await run_audited_mutation(
        plane.audit,
        audit_chain_id(scope.customer_id),
        before=build_before(ctx, make_subject(subject_id, ENTITY_TYPE, state=state)),
        mutate=mutate,
        after=after,
        on_error=failed,
    )


def build_router() -> APIRouter:
    router = APIRouter(tags=["gateways"])

    @router.post(
        "/domains/{domain}/gateways",
        response_model=GatewayRegistration,
        status_code=status.HTTP_201_CREATED,
    )
    async def register_gateway(
        request: Request,
        domain: DomainPath,
        body: RegisterGatewayBody,
        scope: WriteScope,
        plane: Plane,
    ) -> GatewayRegistration:
        return await GatewayApi(plane).register(scope, domain, body, _correlation(request))

    @router.get("/domains/{domain}/gateways", response_model=GatewayList)
    async def list_gateways(
        domain: DomainPath,
        scope: ReadScope,
        plane: Plane,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> GatewayList:
        return await GatewayApi(plane).list(scope, domain, cursor=cursor, limit=limit)

    @router.get("/domains/{domain}/gateways/{gateway_id}", response_model=GatewayDetail)
    async def get_gateway(
        domain: DomainPath, gateway_id: GatewayPath, scope: ReadScope, plane: Plane
    ) -> GatewayDetail:
        return await GatewayApi(plane).detail(scope, domain, gateway_id)

    @router.get(
        "/domains/{domain}/gateways/{gateway_id}/inventory", response_model=GatewayInventory
    )
    async def get_inventory(
        domain: DomainPath, gateway_id: GatewayPath, scope: ReadScope, plane: Plane
    ) -> GatewayInventory:
        return await GatewayApi(plane).inventory(scope, domain, gateway_id)

    @router.post("/domains/{domain}/gateways/{gateway_id}/sync", response_model=GatewayDetail)
    async def sync_gateway(
        request: Request,
        domain: DomainPath,
        gateway_id: GatewayPath,
        scope: WriteScope,
        plane: Plane,
    ) -> GatewayDetail:
        return await GatewayApi(plane).sync(scope, domain, gateway_id, _correlation(request))

    @router.post(
        "/domains/{domain}/gateways/{gateway_id}/mode",
        response_model=ActionView,
        response_model_exclude_unset=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def change_gateway_mode(
        request: Request,
        response: Response,
        domain: DomainPath,
        gateway_id: GatewayPath,
        body: GatewayModeBody,
        scope: ProposeScope,
        plane: Plane,
        actions: Actions,
    ) -> ActionView:
        """Draft the audited ``gateway_mode_change`` intent (the switch runs in the executor)."""
        view, created = await _draft_mode_change(
            plane, actions, scope, domain, gateway_id, body, _correlation(request)
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return view

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
