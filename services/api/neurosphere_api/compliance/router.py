"""Compliance read API (PRP-56 item 5), mounted at ``/api/v1/compliance``.

| Method | Path                                  | Permission      |
|--------|---------------------------------------|-----------------|
| GET    | ``/frameworks``                       | ``evidence.read`` |
| GET    | ``/frameworks/{framework_id}``        | ``evidence.read`` |
| GET    | ``/domains/{domain}/bundle``          | ``evidence.read`` on the domain |
| GET    | ``/domains/{domain}/bundle/export``   | ``evidence.read`` on the domain |

Metadata only. The bundle maps what NeuroSphere observed to framework controls; it does not
determine compliance, and it carries no verdict, score or percentage. ``customer_id`` is never
read from the request: the scope derived from the bearer token names the customer, and the path
``{domain}`` is the authorization target (403 outside it, 503 on a policy-store outage). Each
allowed bundle read appends one allowed-read audit record through ``audited_read`` (PRP-48): it
names the domain and the number of mapped controls; the framework id and digest are in the
response and the export headers.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from neurosphere_contracts.compliance.v1.evidence_bundle import EvidenceBundle
from neurosphere_core.auth.scope import Permission
from neurosphere_core.compliance import (
    ControlLibrary,
    EvidenceSource,
    build_bundle,
    canonical_bytes,
    render_markdown,
)
from neurosphere_core.compliance.bundle import DEFAULT_WINDOW_DAYS
from neurosphere_core.errors import NotFoundError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.authz.read_audit import ReadAudit, audited_read
from neurosphere_api.compliance.dependencies import (
    Clock,
    get_clock,
    get_library,
    get_sources,
)
from neurosphere_api.compliance.models import (
    FrameworkDetailResponse,
    FrameworkListResponse,
    FrameworkSummary,
    MappedControlView,
)
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/compliance"

AuditorScope = Annotated[IdentityScope, Depends(require(Permission.EVIDENCE_READ))]
BundleAudit = Annotated[
    ReadAudit,
    Depends(
        audited_read(Permission.EVIDENCE_READ, "compliance.bundle", domain_from_path("domain"))
    ),
]
ExportAudit = Annotated[
    ReadAudit,
    Depends(
        audited_read(Permission.EVIDENCE_READ, "compliance.export", domain_from_path("domain"))
    ),
]
Library = Annotated[ControlLibrary, Depends(get_library)]
Sources = Annotated[list[EvidenceSource], Depends(get_sources)]
Now = Annotated[Clock, Depends(get_clock)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
FrameworkQuery = Annotated[str, Query(pattern="^[a-z0-9_]{1,64}$")]
WindowDays = Annotated[int, Query(ge=1, le=365)]


async def _bundle(
    audit: ReadAudit,
    library: ControlLibrary,
    sources: list[EvidenceSource],
    clock: Clock,
    domain: str,
    framework_id: str,
    window_days: int,
) -> EvidenceBundle:
    bundle = await build_bundle(
        library,
        framework_id,
        domain,
        audit.scope,  # derived scope only; never a request value
        sources,
        now=clock(),
        window_days=window_days,
    )
    await audit.allowed([domain], len(bundle.controls))
    return bundle


def build_router() -> APIRouter:
    router = APIRouter(tags=["compliance"])

    @router.get("/frameworks", response_model=FrameworkListResponse)
    async def list_frameworks(_scope: AuditorScope, library: Library) -> FrameworkListResponse:
        return FrameworkListResponse(
            library_version=library.version,
            frameworks=[
                FrameworkSummary(
                    framework_id=fw.framework.framework_id.root,
                    title=fw.framework.title,
                    framework_version=fw.framework.framework_version,
                    source_url=fw.framework.source_url,
                    source_retrieved=fw.framework.source_retrieved,
                    control_count=len(fw.controls),
                )
                for fw in library.frameworks
            ],
        )

    @router.get("/frameworks/{framework_id}", response_model=FrameworkDetailResponse)
    async def get_framework(
        framework_id: Annotated[str, Path(pattern="^[a-z0-9_]{1,64}$")],
        _scope: AuditorScope,
        library: Library,
    ) -> FrameworkDetailResponse:
        fw = library.framework(framework_id)
        if fw is None:
            raise NotFoundError("unknown framework", reason="framework_not_found")
        return FrameworkDetailResponse(
            library_version=library.version,
            framework_id=framework_id,
            title=fw.framework.title,
            framework_version=fw.framework.framework_version,
            source_url=fw.framework.source_url,
            source_retrieved=fw.framework.source_retrieved,
            controls=[
                MappedControlView(
                    control_id=m.control.control_id,
                    title=m.control.title,
                    source_url=m.control.source_url,
                    source_retrieved=m.control.source_retrieved,
                    support_status=m.mapping.support_status.root,
                    evidence_sources=[s.root for s in m.mapping.evidence_sources.root],
                )
                for m in fw.controls
            ],
        )

    @router.get("/domains/{domain}/bundle", response_model=EvidenceBundle)
    async def get_bundle(
        domain: DomainPath,
        framework_id: FrameworkQuery,
        audit: BundleAudit,
        library: Library,
        sources: Sources,
        clock: Now,
        window_days: WindowDays = DEFAULT_WINDOW_DAYS,
    ) -> EvidenceBundle:
        return await _bundle(audit, library, sources, clock, domain, framework_id, window_days)

    @router.get("/domains/{domain}/bundle/export")
    async def export_bundle(
        domain: DomainPath,
        framework_id: FrameworkQuery,
        audit: ExportAudit,
        library: Library,
        sources: Sources,
        clock: Now,
        format: Annotated[Literal["json", "md"], Query()] = "json",
        window_days: WindowDays = DEFAULT_WINDOW_DAYS,
    ) -> Response:
        bundle = await _bundle(audit, library, sources, clock, domain, framework_id, window_days)
        if format == "md":
            body = render_markdown(bundle).encode("utf-8")
            media, suffix = "text/markdown; charset=utf-8", "md"
        else:
            body = canonical_bytes(bundle)
            media, suffix = "application/json", "json"
        return Response(
            content=body,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="evidence-{framework_id}.{suffix}"',
                "X-Bundle-Digest": bundle.digest,
                "Cache-Control": "no-store",
            },
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
