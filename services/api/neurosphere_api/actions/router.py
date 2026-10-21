"""Action routes (PRP-17 item 4), mounted at ``/api/v1/actions``.

| Method | Path                                                  | Permission         |
|--------|-------------------------------------------------------|--------------------|
| POST   | ``/domains/{domain}/intents``                         | ``action.propose`` |
| GET    | ``/domains/{domain}/intents``                         | ``data.read``      |
| GET    | ``/domains/{domain}/intents/{intent_id}``             | ``data.read``      |
| POST   | ``/domains/{domain}/intents/{intent_id}/validate``    | ``action.propose`` |
| POST   | ``/domains/{domain}/intents/{intent_id}/confirmation``| ``action.propose`` |
| POST   | ``/domains/{domain}/intents/{intent_id}/confirm``     | ``action.execute`` |
| POST   | ``/domains/{domain}/intents/{intent_id}/decisions``   | ``action.approve`` |
| GET    | ``/emergency-disable``                                | ``data.read``      |
| PUT    | ``/emergency-disable``                                | ``config.manage``  |

The path ``{domain}`` is the authorization TARGET, checked against the server-derived
``IdentityScope`` (403 outside it, 503 on a policy-store outage). ``customer_id``, ``domain_id``
and the maker identity never come from the body or the query. Button, chat, REST and MCP use
these same routes; ``channel`` in the draft body is metadata only. No route applies a change:
``confirm`` and ``decisions`` hand an intent to the executor worker by moving it to
``executing``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from neurosphere_core.actions import IntentKey
from neurosphere_core.auth.scope import Permission
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.emergency import read_control, set_control
from neurosphere_api.actions.models import (
    ActionList,
    ActionView,
    ConfirmBody,
    DecisionBody,
    DraftIntentBody,
    EmergencyDisableBody,
    EmergencyDisableView,
)
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/actions"

ActionState = Literal[
    "drafted",
    "validated",
    "awaiting_confirmation",
    "awaiting_approval",
    "executing",
    "succeeded",
    "failed",
    "rolled_back",
    "expired",
]

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
ProposeScope = Annotated[
    IdentityScope, Depends(require(Permission.ACTION_PROPOSE, domain_from_path("domain")))
]
ExecuteScope = Annotated[
    IdentityScope, Depends(require(Permission.ACTION_EXECUTE, domain_from_path("domain")))
]
ApproveScope = Annotated[
    IdentityScope, Depends(require(Permission.ACTION_APPROVE, domain_from_path("domain")))
]
AnyReadScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
ConfigScope = Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))]
Plane = Annotated[ActionPlane, Depends(get_action_plane)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
IntentPath = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _correlation(request: Request) -> str:
    return audit_correlation_id(correlation_id_of(request.scope))


def _key(scope: IdentityScope, domain: str, intent_id: str) -> IntentKey:
    return IntentKey(scope.customer_id, domain, intent_id)


def build_router() -> APIRouter:
    router = APIRouter(tags=["actions"])

    @router.post(
        "/domains/{domain}/intents",
        response_model=ActionView,
        response_model_exclude_unset=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def draft_intent(
        request: Request,
        response: Response,
        domain: DomainPath,
        body: DraftIntentBody,
        scope: ProposeScope,
        plane: Plane,
    ) -> ActionView:
        view, created = await ActionApi(plane).draft(scope, domain, body, _correlation(request))
        if not created:
            response.status_code = status.HTTP_200_OK
        return view

    @router.get(
        "/domains/{domain}/intents", response_model=ActionList, response_model_exclude_unset=True
    )
    async def list_intents(
        domain: DomainPath,
        scope: ReadScope,
        plane: Plane,
        state: Annotated[ActionState | None, Query()] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> ActionList:
        return await ActionApi(plane).list(scope, domain, state=state, cursor=cursor, limit=limit)

    @router.get(
        "/domains/{domain}/intents/{intent_id}",
        response_model=ActionView,
        response_model_exclude_unset=True,
    )
    async def get_intent(
        domain: DomainPath, intent_id: IntentPath, scope: ReadScope, plane: Plane
    ) -> ActionView:
        return await ActionApi(plane).get(_key(scope, domain, intent_id))

    @router.post(
        "/domains/{domain}/intents/{intent_id}/validate",
        response_model=ActionView,
        response_model_exclude_unset=True,
    )
    async def validate_intent(
        request: Request,
        domain: DomainPath,
        intent_id: IntentPath,
        scope: ProposeScope,
        plane: Plane,
    ) -> ActionView:
        return await ActionApi(plane).validate(
            scope, _key(scope, domain, intent_id), _correlation(request)
        )

    @router.post(
        "/domains/{domain}/intents/{intent_id}/confirmation",
        response_model=ActionView,
        response_model_exclude_unset=True,
    )
    async def present_confirmation(
        request: Request,
        domain: DomainPath,
        intent_id: IntentPath,
        scope: ProposeScope,
        plane: Plane,
    ) -> ActionView:
        return await ActionApi(plane).present_confirmation(
            scope, _key(scope, domain, intent_id), _correlation(request)
        )

    @router.post(
        "/domains/{domain}/intents/{intent_id}/confirm",
        response_model=ActionView,
        response_model_exclude_unset=True,
    )
    async def confirm_intent(
        request: Request,
        domain: DomainPath,
        intent_id: IntentPath,
        body: ConfirmBody,
        scope: ExecuteScope,
        plane: Plane,
    ) -> ActionView:
        return await ActionApi(plane).confirm(
            scope, _key(scope, domain, intent_id), body, _correlation(request)
        )

    @router.post(
        "/domains/{domain}/intents/{intent_id}/decisions",
        response_model=ActionView,
        response_model_exclude_unset=True,
    )
    async def decide_intent(
        request: Request,
        domain: DomainPath,
        intent_id: IntentPath,
        body: DecisionBody,
        scope: ApproveScope,
        plane: Plane,
    ) -> ActionView:
        return await ActionApi(plane).decide(
            scope, _key(scope, domain, intent_id), body, _correlation(request)
        )

    @router.get("/emergency-disable", response_model=EmergencyDisableView)
    async def read_emergency_disable(scope: AnyReadScope, plane: Plane) -> EmergencyDisableView:
        return await read_control(plane, scope)

    @router.put("/emergency-disable", response_model=EmergencyDisableView)
    async def set_emergency_disable(
        request: Request, body: EmergencyDisableBody, scope: ConfigScope, plane: Plane
    ) -> EmergencyDisableView:
        return await set_control(plane, scope, body, _correlation(request))

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
