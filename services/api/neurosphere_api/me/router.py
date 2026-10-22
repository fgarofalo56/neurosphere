"""``GET /api/v1/me/domains`` (PRP-28 item 1): the domains the caller may read.

The list is derived from the server-side ``IdentityScope`` only: exactly the domains where an
unexpired role confers ``data.read`` (``domains_with_permission``), further restricted to the
scope's own cloud and customer. The route takes no query parameters or body, so a caller-supplied
``domain_id``/``customer_id`` cannot influence it. A caller who holds ``data.read`` nowhere gets
403 from ``require``.

Display names come from the catalog repository, read in-process under the caller's scope; with no
repository or no entry the label is derived from the id and flagged ``derived``.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route function.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Request
from neurosphere_core.auth.scope import Permission, domains_with_permission, role_permissions
from neurosphere_core.catalog import CatalogRepository, EntityFilter
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import AuthzState, get_authz_state, require
from neurosphere_api.me.models import DomainView, MeDomains
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "derived_label", "register"]

PREFIX: Final = "/api/v1/me"
_MAX_CATALOG_PAGES: Final = 4
_MAX_FILTER_DOMAINS: Final = 100
_SEPARATORS: Final = re.compile(r"[-_./=]+")

_read_anywhere = require(Permission.DATA_READ)


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
    except DependencyTransientError:
        return names
    return names


def build_router() -> APIRouter:
    router = APIRouter(tags=["me"])

    @router.get("/domains", response_model=MeDomains)
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

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
