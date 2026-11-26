"""Governance policy routes, mounted at ``/api/v1/governance/policy`` (PRP-105 item 6).

Paths below are under ``/domains/{domain}`` (``D``) unless they start with ``/status``; the
permission is checked in ``{domain}``:

| Method | Path                                          | Permission                    |
|--------|-----------------------------------------------|-------------------------------|
| GET    | ``D/policies``                                | ``govpolicy.read``            |
| POST   | ``D/policies``                                | ``govpolicy.manage``          |
| GET    | ``D/policies/{policy_id}`` (``?version=``)    | ``govpolicy.read``            |
| GET    | ``D/policies/{policy_id}/versions``           | ``govpolicy.read``            |
| PUT    | ``D/policies/{policy_id}/draft`` (If-Match)   | ``govpolicy.manage``          |
| POST   | ``D/policies/{policy_id}/publish``            | ``govpolicy.manage``          |
| POST   | ``D/policies/{policy_id}/retire``             | ``govpolicy.manage``          |
| GET    | ``D/violations``                              | ``govpolicy.read``            |
| GET    | ``D/violations/{violation_id}``               | ``govpolicy.read``            |
| POST   | ``D/violations/{violation_id}/exception-requests`` | ``action.propose``       |
| GET    | ``D/exceptions``                              | ``govpolicy.read``            |
| GET    | ``D/bindings``                                | ``govpolicy.read``            |
| GET    | ``/status``                                   | ``govpolicy.read`` (any)      |

Reads go through ``audited_read`` (one allowed-read record per call; denials through the usual
denial recorder). Policy reads answer with ``ETag``; ``PUT .../draft`` requires ``If-Match``.
``publish`` and ``retire`` return the drafted action intent view (201 new, 200 replayed); no route
writes a published state (``service.py``). Disabled or unbuilt -> 503 ``capability_unavailable``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from neurosphere_core.auth.scope import Permission
from neurosphere_core.governance.policy import ExceptionFilters, ViolationFilters
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.actions.models import ActionView
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.authz.read_audit import ReadAudit, audited_read
from neurosphere_api.governance.policy.deps import Plane
from neurosphere_api.governance.policy.models import (
    BindingList,
    ExceptionList,
    ExceptionRequestBody,
    ExceptionRequestView,
    GovernanceStatusView,
    PolicyCreateBody,
    PolicyDraftBody,
    PolicyList,
    PolicyStageBody,
    PolicyView,
    VersionList,
    ViolationList,
    ViolationView,
)
from neurosphere_api.governance.policy.service import GovernancePolicyService
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/governance/policy"

_DOMAIN = domain_from_path("domain")
_SLUG = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_CURSOR = r"^[A-Za-z0-9_\-=.~]+$"

DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
PolicyPath = Annotated[str, Path(pattern=_SLUG)]
ViolationPath = Annotated[str, Path(pattern=_UUID)]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
CursorQuery = Annotated[str | None, Query(min_length=1, max_length=2048, pattern=_CURSOR)]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Severity = Literal["low", "medium", "high", "critical"]

ManageScope = Annotated[IdentityScope, Depends(require(Permission.GOVPOLICY_MANAGE, _DOMAIN))]
ProposeScope = Annotated[IdentityScope, Depends(require(Permission.ACTION_PROPOSE, _DOMAIN))]
PolicyListRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.policy_list", _DOMAIN))
]
PolicyRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.policy_read", _DOMAIN))
]
ViolationListRead = Annotated[
    ReadAudit,
    Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.violation_list", _DOMAIN)),
]
ViolationRead = Annotated[
    ReadAudit,
    Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.violation_read", _DOMAIN)),
]
ExceptionListRead = Annotated[
    ReadAudit,
    Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.exception_list", _DOMAIN)),
]
BindingListRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.binding_list", _DOMAIN))
]
StatusRead = Annotated[
    ReadAudit, Depends(audited_read(Permission.GOVPOLICY_READ, "govpolicy.status_read"))
]
Actions = Annotated[ActionPlane, Depends(get_action_plane)]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def _set_etag(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'


def build_router() -> APIRouter:
    router = APIRouter(tags=["governance-policy"])

    # -- policies ----------------------------------------------------------------------------

    @router.get("/domains/{domain}/policies", response_model=PolicyList)
    async def list_policies(
        domain: DomainPath,
        audit: PolicyListRead,
        plane: Plane,
        cursor: CursorQuery = None,
        limit: LimitQuery = DEFAULT_PAGE_SIZE,
    ) -> PolicyList:
        result = await GovernancePolicyService(plane).list_policies(
            audit.scope, domain, cursor=cursor, limit=limit
        )
        await audit.allowed([domain], len(result.items))
        return result

    @router.post(
        "/domains/{domain}/policies",
        response_model=PolicyView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_policy_draft(
        request: Request,
        response: Response,
        domain: DomainPath,
        body: PolicyCreateBody,
        scope: ManageScope,
        plane: Plane,
    ) -> PolicyView:
        service = GovernancePolicyService(plane)
        stored = await service.create_draft(scope, domain, body, _correlation(request))
        _set_etag(response, stored.etag)
        return service.policy_view(stored)

    @router.get("/domains/{domain}/policies/{policy_id}", response_model=PolicyView)
    async def get_policy(
        response: Response,
        domain: DomainPath,
        policy_id: PolicyPath,
        audit: PolicyRead,
        plane: Plane,
        version: Annotated[int | None, Query(ge=1)] = None,
    ) -> PolicyView:
        service = GovernancePolicyService(plane)
        stored = await service.get_policy(audit.scope, domain, policy_id, version=version)
        await audit.allowed([domain], 1)
        _set_etag(response, stored.etag)
        return service.policy_view(stored)

    @router.get("/domains/{domain}/policies/{policy_id}/versions", response_model=VersionList)
    async def list_policy_versions(
        domain: DomainPath, policy_id: PolicyPath, audit: PolicyRead, plane: Plane
    ) -> VersionList:
        result = await GovernancePolicyService(plane).versions(audit.scope, domain, policy_id)
        await audit.allowed([domain], len(result.items))
        return result

    @router.put("/domains/{domain}/policies/{policy_id}/draft", response_model=PolicyView)
    async def replace_policy_draft(
        request: Request,
        response: Response,
        domain: DomainPath,
        policy_id: PolicyPath,
        body: PolicyDraftBody,
        if_match: IfMatch,
        scope: ManageScope,
        plane: Plane,
    ) -> PolicyView:
        service = GovernancePolicyService(plane)
        stored = await service.replace_draft(
            scope,
            domain,
            policy_id,
            body,
            if_match=if_match,
            correlation_id=_correlation(request),
        )
        _set_etag(response, stored.etag)
        return service.policy_view(stored)

    @router.post(
        "/domains/{domain}/policies/{policy_id}/publish",
        response_model=ActionView,
        response_model_exclude_unset=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def draft_policy_publish(
        request: Request,
        response: Response,
        domain: DomainPath,
        policy_id: PolicyPath,
        body: PolicyStageBody,
        scope: ManageScope,
        plane: Plane,
        actions: Actions,
    ) -> ActionView:
        view, created = await GovernancePolicyService(plane).draft_stage_intent(
            actions, scope, domain, policy_id, "publish", body, _correlation(request)
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return view

    @router.post(
        "/domains/{domain}/policies/{policy_id}/retire",
        response_model=ActionView,
        response_model_exclude_unset=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def draft_policy_retire(
        request: Request,
        response: Response,
        domain: DomainPath,
        policy_id: PolicyPath,
        body: PolicyStageBody,
        scope: ManageScope,
        plane: Plane,
        actions: Actions,
    ) -> ActionView:
        view, created = await GovernancePolicyService(plane).draft_stage_intent(
            actions, scope, domain, policy_id, "retire", body, _correlation(request)
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return view

    # -- violations and exceptions -----------------------------------------------------------

    @router.get("/domains/{domain}/violations", response_model=ViolationList)
    async def list_violations(
        domain: DomainPath,
        audit: ViolationListRead,
        plane: Plane,
        violation_status: Annotated[
            Literal["open", "excepted", "resolved", "superseded"] | None, Query(alias="status")
        ] = None,
        policy_id: Annotated[str | None, Query(pattern=_SLUG)] = None,
        rule_id: Annotated[str | None, Query(pattern=_SLUG)] = None,
        severity: Annotated[Severity | None, Query()] = None,
        cursor: CursorQuery = None,
        limit: LimitQuery = DEFAULT_PAGE_SIZE,
    ) -> ViolationList:
        filters = ViolationFilters(
            domain_ids=(domain,),
            status=violation_status,
            policy_id=policy_id,
            rule_id=rule_id,
            severity=severity,
        )
        result = await GovernancePolicyService(plane).list_violations(
            audit.scope, domain, filters, cursor=cursor, limit=limit
        )
        await audit.allowed([domain], len(result.items))
        return result

    @router.get("/domains/{domain}/violations/{violation_id}", response_model=ViolationView)
    async def get_violation(
        domain: DomainPath, violation_id: ViolationPath, audit: ViolationRead, plane: Plane
    ) -> ViolationView:
        service = GovernancePolicyService(plane)
        stored = await service.get_violation(audit.scope, domain, violation_id)
        await audit.allowed([domain], 1)
        return service.violation_view(stored)

    @router.post(
        "/domains/{domain}/violations/{violation_id}/exception-requests",
        response_model=ExceptionRequestView,
        status_code=status.HTTP_201_CREATED,
    )
    async def request_policy_exception(
        request: Request,
        domain: DomainPath,
        violation_id: ViolationPath,
        body: ExceptionRequestBody,
        scope: ProposeScope,
        plane: Plane,
    ) -> ExceptionRequestView:
        return await GovernancePolicyService(plane).request_exception(
            scope, domain, violation_id, body, correlation_id=_correlation(request)
        )

    @router.get("/domains/{domain}/exceptions", response_model=ExceptionList)
    async def list_exceptions(
        domain: DomainPath,
        audit: ExceptionListRead,
        plane: Plane,
        exception_status: Annotated[
            Literal["requested", "approved", "rejected", "expired", "revoked"] | None,
            Query(alias="status"),
        ] = None,
        policy_id: Annotated[str | None, Query(pattern=_SLUG)] = None,
        violation_id: Annotated[str | None, Query(pattern=_UUID)] = None,
        cursor: CursorQuery = None,
        limit: LimitQuery = DEFAULT_PAGE_SIZE,
    ) -> ExceptionList:
        filters = ExceptionFilters(
            domain_ids=(domain,),
            status=exception_status,
            policy_id=policy_id,
            violation_id=violation_id,
        )
        result = await GovernancePolicyService(plane).list_exceptions(
            audit.scope, domain, filters, cursor=cursor, limit=limit
        )
        await audit.allowed([domain], len(result.items))
        return result

    # -- bindings and status -----------------------------------------------------------------

    @router.get("/domains/{domain}/bindings", response_model=BindingList)
    async def list_bindings(
        domain: DomainPath,
        audit: BindingListRead,
        plane: Plane,
        policy_id: Annotated[str | None, Query(pattern=_SLUG)] = None,
        point: Annotated[
            Literal[
                "gateway", "tool_call", "mcp_server", "mcp_client", "sdk", "budget", "registration"
            ]
            | None,
            Query(),
        ] = None,
    ) -> BindingList:
        result = await GovernancePolicyService(plane).list_bindings(
            audit.scope, domain, policy_id=policy_id, point=point
        )
        await audit.allowed([domain], len(result.items))
        return result

    @router.get("/status", response_model=GovernanceStatusView)
    async def governance_policy_status(audit: StatusRead, plane: Plane) -> GovernanceStatusView:
        result = await GovernancePolicyService(plane).status(audit.scope)
        await audit.allowed([run.domain_id for run in result.runs], len(result.runs))
        return result

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
