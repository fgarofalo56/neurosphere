"""Identity admin policy routes, mounted at ``/api/v1/admin/identity`` (PRP-39 item 3).

| Method     | Path                                                         | Permission      |
|------------|--------------------------------------------------------------|-----------------|
| GET        | ``/principals``                                              | ``policy.manage`` |
| GET        | ``/principals/{principal_id}``                               | ``policy.manage`` |
| PUT/DELETE | ``/principals/{principal_id}/role-assignments/{assignment_id}`` | ``policy.manage`` |
| PUT/DELETE | ``/principals/{principal_id}/domain-memberships/{domain_id}`` | ``policy.manage`` |
| PUT/DELETE | ``/principals/{principal_id}/grants/{grant_id}``             | ``policy.manage`` |

``require(policy.manage)`` (held in at least one domain) is only the first gate: the service
then checks every domain the change names, self-modification and customer-wide authority (see
``service``). Writes to an existing document need ``If-Match`` (the ``ETag`` of the last read);
every response carries the new ``ETag``. ``principal_id`` must be a canonical pseudonymous id;
an invalid value is refused by pattern and never echoed (it could be a UPN).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from neurosphere_contracts.admin.v1.domain_membership_change import DomainMembershipChange
from neurosphere_contracts.admin.v1.principal_access_summary import PrincipalAccessSummary
from neurosphere_contracts.admin.v1.resource_grant_change import ResourceGrantChange
from neurosphere_contracts.admin.v1.role_assignment_change import RoleAssignmentChange
from neurosphere_core.auth.revocation import PRINCIPAL_ID_PATTERN, REASON_CODE_PATTERN
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.scope import IdentityScope

from neurosphere_api.admin.identity.models import (
    ADMIN_SCHEMA_VERSION,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    PrincipalPage,
)
from neurosphere_api.admin.identity.plane import IdentityAdminPlane, get_plane
from neurosphere_api.admin.identity.service import IdentityAdminService, PolicyWriteResult
from neurosphere_api.authz import AuthzState, get_authz_state, require

__all__ = [
    "DEFAULT_REMOVE_REASON",
    "IfMatch",
    "PrincipalPath",
    "ReasonQuery",
    "build_router",
]

DEFAULT_REMOVE_REASON: Final = "removed_by_administrator"

PolicyScope = Annotated[IdentityScope, Depends(require(Permission.POLICY_MANAGE))]
PrincipalPath = Annotated[str, Path(pattern=PRINCIPAL_ID_PATTERN, max_length=512)]
RecordPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]
DomainPath = Annotated[
    str,
    Path(
        pattern=r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$",
        max_length=512,
    ),
]
IfMatch = Annotated[str | None, Header(alias="If-Match", min_length=1, max_length=300)]
ReasonQuery = Annotated[str, Query(pattern=REASON_CODE_PATTERN)]


def _service(
    request: Request,
    scope: PolicyScope,
    state: Annotated[AuthzState, Depends(get_authz_state)],
    plane: Annotated[IdentityAdminPlane, Depends(get_plane)],
) -> IdentityAdminService:
    return IdentityAdminService(plane, state, request, scope)


Service = Annotated[IdentityAdminService, Depends(_service)]


def _respond(response: Response, result: PolicyWriteResult) -> PrincipalAccessSummary:
    etag = result.etag
    if etag:
        response.headers["ETag"] = etag if etag.startswith('"') else f'"{etag}"'
    return result.summary


def _op(expected: str, actual: str) -> None:
    if actual != expected:
        raise InvalidSchemaError(
            f"this method only accepts op={expected}",
            errors=[ValidationIssue("/op", f"must be {expected}")],
            reason="op_not_allowed",
        )


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-identity"])

    @router.get("/principals", response_model=PrincipalPage)
    async def list_principals(
        service: Service,
        cursor: Annotated[str | None, Query(pattern=PRINCIPAL_ID_PATTERN)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    ) -> PrincipalPage:
        return await service.list_principals(cursor=cursor, limit=limit)

    @router.get("/principals/{principal_id}", response_model=PrincipalAccessSummary)
    async def get_principal(
        response: Response, principal_id: PrincipalPath, service: Service
    ) -> PrincipalAccessSummary:
        return _respond(response, await service.get_principal(principal_id))

    @router.put(
        "/principals/{principal_id}/role-assignments/{assignment_id}",
        response_model=PrincipalAccessSummary,
    )
    async def put_role_assignment(
        response: Response,
        principal_id: PrincipalPath,
        assignment_id: RecordPath,
        body: RoleAssignmentChange,
        service: Service,
        if_match: IfMatch = None,
    ) -> PrincipalAccessSummary:
        _op("assign", body.op)
        result = await service.put_role(principal_id, assignment_id, body, if_match)
        return _respond(response, result)

    @router.delete(
        "/principals/{principal_id}/role-assignments/{assignment_id}",
        response_model=PrincipalAccessSummary,
    )
    async def delete_role_assignment(
        response: Response,
        principal_id: PrincipalPath,
        assignment_id: RecordPath,
        service: Service,
        if_match: IfMatch = None,
        reason: ReasonQuery = DEFAULT_REMOVE_REASON,
    ) -> PrincipalAccessSummary:
        result = await service.remove_role(
            principal_id, assignment_id, reason=reason, if_match=if_match
        )
        return _respond(response, result)

    @router.put(
        "/principals/{principal_id}/domain-memberships/{domain_id:path}",
        response_model=PrincipalAccessSummary,
    )
    async def put_domain_membership(
        response: Response,
        principal_id: PrincipalPath,
        domain_id: DomainPath,
        body: DomainMembershipChange,
        service: Service,
        if_match: IfMatch = None,
    ) -> PrincipalAccessSummary:
        _op("add", body.op)
        result = await service.change_membership(principal_id, domain_id, body, if_match)
        return _respond(response, result)

    @router.delete(
        "/principals/{principal_id}/domain-memberships/{domain_id:path}",
        response_model=PrincipalAccessSummary,
    )
    async def delete_domain_membership(
        response: Response,
        principal_id: PrincipalPath,
        domain_id: DomainPath,
        service: Service,
        if_match: IfMatch = None,
        reason: ReasonQuery = DEFAULT_REMOVE_REASON,
    ) -> PrincipalAccessSummary:
        change = DomainMembershipChange.model_validate(
            {
                "schema_version": ADMIN_SCHEMA_VERSION,
                "op": "remove",
                "principal_id": principal_id,
                "domain_id": domain_id,
                "reason": reason,
            }
        )
        result = await service.change_membership(principal_id, domain_id, change, if_match)
        return _respond(response, result)

    @router.put(
        "/principals/{principal_id}/grants/{grant_id}", response_model=PrincipalAccessSummary
    )
    async def put_grant(
        response: Response,
        principal_id: PrincipalPath,
        grant_id: RecordPath,
        body: ResourceGrantChange,
        service: Service,
        if_match: IfMatch = None,
    ) -> PrincipalAccessSummary:
        result = await service.put_grant(principal_id, grant_id, body, if_match)
        return _respond(response, result)

    @router.delete(
        "/principals/{principal_id}/grants/{grant_id}", response_model=PrincipalAccessSummary
    )
    async def delete_grant(
        response: Response,
        principal_id: PrincipalPath,
        grant_id: RecordPath,
        service: Service,
        if_match: IfMatch = None,
    ) -> PrincipalAccessSummary:
        result = await service.remove_grant(principal_id, grant_id, if_match=if_match)
        return _respond(response, result)

    return router
