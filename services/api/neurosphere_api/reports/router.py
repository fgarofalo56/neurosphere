"""Saved-report routes (PRP-19 item 5), mounted at ``/api/v1/reports``.

| Method | Path                                                   | Permission |
|--------|--------------------------------------------------------|------------|
| POST | ``/domains/{domain_id}/reports``                       | ``report.create`` |
| GET | ``/domains/{domain_id}/reports``                       | ``data.read`` |
| GET | ``.../reports/{report_id}``                            | ``data.read`` + owner/share/pub. |
| PUT | ``.../reports/{report_id}`` (``If-Match``)             | ``report.create`` + owner |
| DELETE | ``.../reports/{report_id}`` (``If-Match``)             | ``report.create`` + owner |
| POST | ``.../reports/{report_id}/run``                        | ``data.read`` + owner/share/pub. |
| POST | ``.../reports/{report_id}/shares``                     | ``report.create`` + owner |
| DELETE | ``.../reports/{report_id}/shares/{principal_id}``      | ``report.create`` + owner |
| POST | ``.../reports/{report_id}/publication``                | ``report.create`` + owner |
| POST | ``.../reports/{report_id}/publication/decision`` | ``config.manage`` (not owner) |

The path ``domain_id`` is the authorization TARGET. A report the caller may not see is 404; a
visible report the caller may not change is 403 ``not_owner``. Every mutation returns the new
``ETag``; ``PUT`` and ``DELETE`` require ``If-Match`` (mismatch -> 409 ``stale_version``).
Nothing here stores or returns another viewer's data: ``run`` evaluates the stored query as the
caller.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.reports.dependencies import get_report_service
from neurosphere_api.reports.models import (
    DecisionBody,
    PublicationState,
    ReportBody,
    ReportList,
    ReportView,
    RunView,
    ShareBody,
    StoredReport,
)
from neurosphere_api.reports.service import ReportService
from neurosphere_api.reports.store import DEFAULT_LIMIT, MAX_LIMIT
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/reports"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain_id")))
]
CreateScope = Annotated[
    IdentityScope, Depends(require(Permission.REPORT_CREATE, domain_from_path("domain_id")))
]
ConfigScope = Annotated[
    IdentityScope, Depends(require(Permission.CONFIG_MANAGE, domain_from_path("domain_id")))
]
Service = Annotated[ReportService, Depends(get_report_service)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
ReportPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
PrincipalPath = Annotated[str, Path(min_length=3, max_length=512, pattern=r"^[A-Za-z0-9:._/=-]+$")]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
OptionalIfMatch = Annotated[str | None, Header(alias="If-Match", min_length=1, max_length=300)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def _respond(
    service: ReportService, response: Response, scope: IdentityScope, report: StoredReport
) -> ReportView:
    view = service.view(scope, report)
    response.headers["ETag"] = view.etag
    return view


def build_router() -> APIRouter:
    router = APIRouter(tags=["reports"])
    base = "/domains/{domain_id}/reports"
    item = base + "/{report_id}"

    @router.post(base, response_model=ReportView, status_code=status.HTTP_201_CREATED)
    async def create_report(
        response: Response,
        domain_id: DomainPath,
        body: ReportBody,
        scope: CreateScope,
        service: Service,
    ) -> ReportView:
        return _respond(service, response, scope, await service.create(scope, domain_id, body))

    @router.get(base, response_model=ReportList)
    async def list_reports(
        domain_id: DomainPath,
        scope: ReadScope,
        service: Service,
        publication_state: Annotated[PublicationState | None, Query()] = None,
        cursor: Cursor = None,
        limit: PageLimit = DEFAULT_LIMIT,
    ) -> ReportList:
        page = await service.list(
            scope, domain_id, publication_state=publication_state, cursor=cursor, limit=limit
        )
        return ReportList(
            items=[service.view(scope, r) for r in page.items], next_cursor=page.next_cursor
        )

    @router.get(item, response_model=ReportView)
    async def get_report(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        scope: ReadScope,
        service: Service,
    ) -> ReportView:
        return _respond(service, response, scope, await service.get(scope, domain_id, report_id))

    @router.put(item, response_model=ReportView)
    async def update_report(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        body: ReportBody,
        if_match: IfMatch,
        scope: CreateScope,
        service: Service,
    ) -> ReportView:
        report = await service.update(scope, domain_id, report_id, body, if_match)
        return _respond(service, response, scope, report)

    @router.delete(item, status_code=status.HTTP_204_NO_CONTENT)
    async def delete_report(
        domain_id: DomainPath,
        report_id: ReportPath,
        if_match: IfMatch,
        scope: CreateScope,
        service: Service,
    ) -> Response:
        await service.delete(scope, domain_id, report_id, if_match)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(item + "/run", response_model=RunView)
    async def run_report(
        domain_id: DomainPath, report_id: ReportPath, scope: ReadScope, service: Service
    ) -> RunView:
        return await service.run(scope, domain_id, report_id)

    @router.post(item + "/shares", response_model=ReportView)
    async def share_report(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        body: ShareBody,
        scope: CreateScope,
        service: Service,
        if_match: OptionalIfMatch = None,
    ) -> ReportView:
        report = await service.share(scope, domain_id, report_id, body.principal_id, if_match)
        return _respond(service, response, scope, report)

    @router.delete(item + "/shares/{principal_id}", response_model=ReportView)
    async def unshare_report(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        principal_id: PrincipalPath,
        scope: CreateScope,
        service: Service,
        if_match: OptionalIfMatch = None,
    ) -> ReportView:
        report = await service.unshare(scope, domain_id, report_id, principal_id, if_match)
        return _respond(service, response, scope, report)

    @router.post(item + "/publication", response_model=ReportView)
    async def request_publication(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        scope: CreateScope,
        service: Service,
        if_match: OptionalIfMatch = None,
    ) -> ReportView:
        report = await service.request_publication(scope, domain_id, report_id, if_match)
        return _respond(service, response, scope, report)

    @router.post(item + "/publication/decision", response_model=ReportView)
    async def decide_publication(
        response: Response,
        domain_id: DomainPath,
        report_id: ReportPath,
        body: DecisionBody,
        scope: ConfigScope,
        service: Service,
        if_match: OptionalIfMatch = None,
    ) -> ReportView:
        report = await service.decide_publication(scope, domain_id, report_id, body, if_match)
        return _respond(service, response, scope, report)

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
