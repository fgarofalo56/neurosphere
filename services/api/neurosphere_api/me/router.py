"""``GET /api/v1/me/domains`` (PRP-28 item 1) and ``GET /api/v1/me/access`` (PRP-138 item 5).

``/me/access`` is the authenticated-self route (``AUTHENTICATED_SELF_PATHS``): any caller with a
valid token, no permission, answered from the caller's own derivation only (``me.access``).

``/me/domains``: the domains the caller may read.

The list is derived from the server-side ``IdentityScope`` only: exactly the domains where an
unexpired role confers ``data.read`` (``domains_with_permission``), further restricted to the
scope's own cloud and customer. The route takes no query parameters or body, so a caller-supplied
``domain_id``/``customer_id`` cannot influence it. A caller who holds ``data.read`` nowhere gets
403 from ``require``. A caller whose only ``data.read`` comes from a resource-scoped grant passes
``require`` (a grant is ``data.read`` on one resource) but reads no domain: 200 with an empty
list, documented in the OpenAPI description (PRP-48 item 2, #91).

Display names come from the catalog repository, read in-process under the caller's scope; with no
repository or no entry the label is derived from the id and flagged ``derived``. The catalog
lookup reads at most ``_MAX_CATALOG_PAGES`` pages; hitting that cap logs one warning carrying the
domain count only (never a domain id) and the remaining labels fall back to ``derived``.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route function.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import (
    Permission,
    ScopeDerivation,
    domains_with_permission,
    role_permissions,
)
from neurosphere_core.catalog import CatalogRepository, EntityFilter
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.observability import get_logger
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.admin.identity.role_mapping import mapping_configured
from neurosphere_api.authz import (
    AuthzState,
    get_authz_state,
    groups_overage_of,
    require,
    require_authenticated,
)
from neurosphere_api.me.access import access_view
from neurosphere_api.me.models import DomainView, MeAccess, MeDomains
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "derived_label", "register"]

PREFIX: Final = "/api/v1/me"
_MAX_CATALOG_PAGES: Final = 4
_MAX_FILTER_DOMAINS: Final = 100
_SEPARATORS: Final = re.compile(r"[-_./=]+")
_LOG = get_logger("neurosphere_api.me")

_DOMAINS_DESCRIPTION: Final = (
    "The domains the caller may read (an unexpired role conferring `data.read`, in the caller's "
    "own cloud and customer), with display names from the catalog. A caller whose only "
    "`data.read` comes from a resource-scoped grant gets **200 with an empty `items` list**: the "
    "grant covers one resource, never a domain. A caller holding `data.read` nowhere gets 403."
)

_ACCESS_DESCRIPTION: Final = (
    "The caller's own role assignments and where each came from: `entra_app_role` or "
    "`entra_group` (applied from the deployment's Entra claim role mapping, with the mapping "
    "entry id) or `policy_store`. Per role: domain count, whether it covers the customer control "
    "domain, and its expiry. Any authenticated caller may read it, including one with no role "
    "(**200 with an empty `roles` list**). Never returns domain ids, claim values, group object "
    "ids, the mapping itself or anything about another principal."
)

_read_anywhere = require(Permission.DATA_READ)
_authenticated = require_authenticated()


def derived_label(domain_id: str) -> str:
    """Readable label from the id's last segment (``...:domain:data-science`` -> Data Science)."""
    tail = domain_id.rsplit(":", 1)[-1]
    words = [w for w in _SEPARATORS.split(tail) if w]
    return " ".join(w.capitalize() for w in words) or domain_id


def _in_scope_tenancy(scope: IdentityScope, domain_id: str) -> bool:
    parts = domain_id.split(":")
    return len(parts) >= 2 and parts[0] == str(scope.cloud) and parts[1] == scope.customer_id


def _expired(expires_at: str | None, now: datetime) -> bool:
    return expires_at is not None and now >= datetime.fromisoformat(
        expires_at.replace("Z", "+00:00")
    )


def _permissions_for(scope: IdentityScope, domain_id: str, now: datetime) -> list[str]:
    held: set[str] = set()
    for assignment in scope.to_contract().roles:
        expires = assignment.expires_at
        if _expired(None if expires is None else expires.root, now):
            continue
        if domain_id in {d.root for d in assignment.domain_ids}:
            held.update(str(p) for p in role_permissions(assignment.role))
    return sorted(held)


async def _catalog_names(
    request: Request, scope: IdentityScope, domain_ids: frozenset[str]
) -> dict[str, str]:
    repository = getattr(request.app.state, "catalog_repository", None)
    if not isinstance(repository, CatalogRepository):
        return {}
    flt = EntityFilter(
        entity_types=["domain"],
        domain_ids=sorted(domain_ids) if len(domain_ids) <= _MAX_FILTER_DOMAINS else None,
    )
    names: dict[str, str] = {}
    cursor = None
    try:
        for _ in range(_MAX_CATALOG_PAGES):
            page = await repository.list_entities(scope, flt, PageRequest(cursor=cursor))
            for entity in page.items:
                name = getattr(entity, "display_name", None)
                name = getattr(name, "root", name)
                if entity.id in domain_ids and isinstance(name, str) and name.strip():
                    names[entity.id] = name.strip()
            cursor = page.next_cursor
            if cursor is None:
                break
        else:
            # Cap reached with pages left: the rest keep derived labels. Count only, no ids.
            _LOG.warning(
                "me/domains catalog lookup hit the page cap; remaining labels are derived",
                extra={"domain_count": len(domain_ids), "page_cap": _MAX_CATALOG_PAGES},
            )
    except DependencyTransientError:
        return names
    return names


def build_router() -> APIRouter:
    router = APIRouter(tags=["me"])

    @router.get("/domains", response_model=MeDomains, description=_DOMAINS_DESCRIPTION)
    async def my_domains(
        request: Request,
        scope: Annotated[IdentityScope, Depends(_read_anywhere)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> MeDomains:
        now = datetime.fromtimestamp(state.clock(), UTC)
        readable = frozenset(
            d
            for d in domains_with_permission(scope, Permission.DATA_READ, now=now)
            if _in_scope_tenancy(scope, d)
        )
        names = await _catalog_names(request, scope, readable)
        items = [
            DomainView(
                domain_id=d,
                display_name=names.get(d) or derived_label(d),
                display_name_source="catalog" if d in names else "derived",
                cloud=cast("Literal['commercial', 'government']", d.split(":", 1)[0]),
                permissions=_permissions_for(scope, d, now),
            )
            for d in readable
        ]
        items.sort(key=lambda v: (v.display_name, v.domain_id))
        return MeDomains(items=items)

    @router.get("/access", response_model=MeAccess, description=_ACCESS_DESCRIPTION)
    async def my_access(
        request: Request,
        derivation: Annotated[ScopeDerivation, Depends(_authenticated)],
    ) -> MeAccess:
        return access_view(
            derivation,
            mapping_configured=mapping_configured(request.app.state),
            groups_overage=groups_overage_of(request),
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
