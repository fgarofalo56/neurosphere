"""Thin HTTP handler for the resource scan. Logic lives in :class:`ScanService`.

The service lives on ``app.state.scan_service`` (set with :func:`configure_scan`); until it is
configured the route fails closed with 503. The route is gated by ``config.manage``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.deploy.scan.audit import DeployAuditor, correlation_for
from neurosphere_api.deploy.scan.models import ScanRequest, ScanResponse
from neurosphere_api.deploy.scan.service import ScanService
from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

ROUTE_PREFIX = "/api/v1/deploy/scan"
#: Deprecated alias for one release (PRP-29 item 4): same router, same permissions.
ALIAS_PREFIX = "/v1/deploy/scan"


def configure_scan(app: FastAPI, service: ScanService) -> None:
    app.state.scan_service = service


def _service(request: Request) -> ScanService:
    service = getattr(request.app.state, "scan_service", None)
    if not isinstance(service, ScanService):
        raise DependencyTransientError("Scan is not configured.", reason="scan_not_configured")
    return service


def auditor_for(request: Request, scope: IdentityScope) -> DeployAuditor:
    """Per-request auditor over ``app.state.audit_repository``; fails closed when unset."""
    repository = getattr(request.app.state, "audit_repository", None)
    return DeployAuditor(
        repository if isinstance(repository, AuditRepository) else None,
        scope,
        correlation_id=correlation_for(correlation_id_of(request.scope)),
    )


def build_router() -> APIRouter:
    router = APIRouter(tags=["deploy"])

    @router.post("", response_model=ScanResponse)
    async def scan(
        body: ScanRequest,
        request: Request,
        scope: Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))],
    ) -> ScanResponse:
        return await _service(request).scan_for(scope, body, auditor_for(request, scope))

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    register_with_alias(registry, build_router(), prefix=ROUTE_PREFIX, alias_prefix=ALIAS_PREFIX)
