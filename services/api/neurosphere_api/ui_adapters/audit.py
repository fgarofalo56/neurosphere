"""Domain-path audit reads for the browser (PRP-31 item 2), mounted at ``/api/v1/audit/domains``.

| Method | Path                    | Permission                       |
|--------|-------------------------|----------------------------------|
| GET    | ``""`` (the list)       | ``audit.read`` (any domain)      |
| GET    | ``/{domain}/records``   | ``audit.read`` on ``{domain}``   |
| GET    | ``/{domain}/verify``    | ``audit.read`` on ``{domain}``   |

An auditor holds ``audit.read``/``evidence.read`` and no ``data.read``, so ``/api/v1/me/domains``
answers 403 for them. The list route here derives the auditable domains from the same server-side
scope (``domains_with_permission(scope, audit.read)``), restricted to the scope's own cloud and
customer, and answers 403 when none remain.

The chain id is NEVER typed by the browser: it is ``action_audit_chain_id(scope.customer_id,
domain)``, i.e. ``<customer>.<domain name>``. Because that convention keys a chain by the domain's
last segment only, a domain is auditable here only when it round-trips: the PRP-06 mount maps the
derived chain back to exactly ``{domain}`` (``domain_from_chain_id``). Anything else -- another
customer's or cloud's domain, or a domain whose chain would alias a different domain -- is 403
``audit_chain_out_of_scope`` and is recorded as a denied attempt. The permission is then checked on
``{domain}`` itself (no customer-level fallback), so a cross-domain read is 403 too.

Records are paged by sequence exactly like ``GET /api/v1/audit/chains/{chain_id}/records``;
verification returns the repository's ``ChainVerification`` unchanged.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.actions.audit import action_audit_chain_id
from neurosphere_core.audit import AuditRepository, ChainVerification
from neurosphere_core.audit.repository import MAX_RANGE
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.catalog import CatalogRepository, EntityFilter
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit import get_audit_repository
from neurosphere_api.authz import (
    AuthzState,
    AuthzTarget,
    domain_from_chain_id,
    domain_from_path,
    get_authz_state,
    require,
)
from neurosphere_api.me import derived_label
from neurosphere_api.ui_adapters.catalog import DomainPath
from neurosphere_api.ui_adapters.models import AuditDomainList, AuditDomainView

__all__ = ["PREFIX", "auditable_chain", "build_router"]

PREFIX: Final = "/api/v1/audit/domains"
_MAX_NAME_LOOKUP: Final = 100
_by_path = domain_from_path("domain")


def auditable_chain(scope: IdentityScope, domain_id: str) -> str | None:
    """The chain of ``domain_id`` for ``scope``, or ``None`` when it does not round-trip.

    ``None`` for another cloud or customer, and for a domain whose ``<customer>.<name>`` chain
    the audit mount would attribute to a different domain id.
    """
    parts = domain_id.split(":")
    if len(parts) < 2 or parts[0] != str(scope.cloud) or parts[1] != scope.customer_id:
        return None
    chain = action_audit_chain_id(scope.customer_id, domain_id)
    return chain if domain_from_chain_id(scope, chain) == domain_id else None


def _audit_domain(request: Request, scope: IdentityScope) -> AuthzTarget | None:
    target = _by_path(request, scope)
    if target is not None and auditable_chain(scope, target.domain_id or "") is None:
        raise ForbiddenError(
            "audit chain is outside the caller's scope", reason="audit_chain_out_of_scope"
        )
    return target


AuditAnywhere = Annotated[IdentityScope, Depends(require(Permission.AUDIT_READ))]
AuditDomain = Annotated[
    IdentityScope, Depends(require(Permission.AUDIT_READ, resource=_audit_domain))
]
Repository = Annotated[AuditRepository, Depends(get_audit_repository)]
CursorParam = Annotated[str | None, Query(pattern=r"^[0-9]{1,18}$")]
PageSizeParam = Annotated[int, Query(ge=1, le=MAX_RANGE)]


def _chain(scope: IdentityScope, domain: str) -> str:
    chain = auditable_chain(scope, domain)
    if chain is None:  # pragma: no cover - the permission dependency already refused it
        raise ForbiddenError(
            "audit chain is outside the caller's scope", reason="audit_chain_out_of_scope"
        )
    return chain


async def _catalog_names(
    request: Request, scope: IdentityScope, domain_ids: list[str]
) -> dict[str, str]:
    """Display names the caller may read (scope-filtered by the repository); one page at most.

    An auditor without ``data.read`` reads nothing here, so their labels are derived.
    """
    repository = getattr(request.app.state, "catalog_repository", None)
    if not isinstance(repository, CatalogRepository) or not domain_ids:
        return {}
    wanted = set(domain_ids)
    flt = EntityFilter(
        entity_types=["domain"],
        domain_ids=sorted(wanted) if len(wanted) <= _MAX_NAME_LOOKUP else None,
    )
    try:
        page = await repository.list_entities(scope, flt, PageRequest(page_size=500))
    except DependencyTransientError:
        return {}
    names: dict[str, str] = {}
    for entity in page.items:
        name = getattr(entity, "display_name", None)
        name = getattr(name, "root", name)
        if entity.id in wanted and isinstance(name, str) and name.strip():
            names[entity.id] = name.strip()
    return names


def build_router() -> APIRouter:
    router = APIRouter(tags=["ui-adapters"])

    @router.get("", response_model=AuditDomainList)
    async def audit_domains(
        request: Request,
        scope: AuditAnywhere,
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> AuditDomainList:
        now = datetime.fromtimestamp(state.clock(), UTC)
        domains = sorted(
            d
            for d in domains_with_permission(scope, Permission.AUDIT_READ, now=now)
            if auditable_chain(scope, d) is not None
        )
        if not domains:
            raise ForbiddenError("no auditable domain in scope", reason="permission_missing")
        names = await _catalog_names(request, scope, domains)
        items = [
            AuditDomainView(
                domain_id=d,
                display_name=names.get(d) or derived_label(d),
                display_name_source="catalog" if d in names else "derived",
            )
            for d in domains
        ]
        items.sort(key=lambda v: (v.display_name, v.domain_id))
        return AuditDomainList(items=items)

    @router.get("/{domain}/records", response_model=Page[AuditRecord])
    async def audit_domain_records(
        domain: DomainPath,
        scope: AuditDomain,
        repository: Repository,
        cursor: CursorParam = None,
        page_size: PageSizeParam = DEFAULT_PAGE_SIZE,
    ) -> Page[AuditRecord]:
        chain = _chain(scope, domain)
        start = int(cursor) if cursor is not None else 0
        records = await repository.read_range(chain, start=start, limit=page_size)
        tail = await repository.tail(chain)
        next_start = start + page_size
        more = tail is not None and next_start <= tail.sequence
        return Page[AuditRecord](
            items=tuple(records), next_cursor=str(next_start) if more else None
        )

    @router.get("/{domain}/verify", response_model=ChainVerification)
    async def audit_domain_verify(
        domain: DomainPath, scope: AuditDomain, repository: Repository
    ) -> ChainVerification:
        return await repository.verify(_chain(scope, domain))

    return router
