"""Store-backed readers: gateway inventories and catalog model deployments (PRP-61 item 3).

Both read through scope-filtered or domain-keyed store protocols already used elsewhere, and copy
out names only: the gateway reader keeps policy-fragment *names* (the fragment XML is never in
the inventory), the catalog reader keeps the ``foundry_project`` attribute of
``model_deployment`` entities.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from neurosphere_core.catalog.protocol import EntityFilter
from neurosphere_core.detections import CatalogRead, GatewayFragments, GatewayRead
from neurosphere_core.paging import PageRequest

__all__ = ["CatalogProjectReader", "StoreGatewayReader"]

logger = logging.getLogger(__name__)

_PAGE = 100


class StoreGatewayReader:
    def __init__(
        self,
        store: GatewayLister,
        customer_id: str,
        domain_ids: Sequence[str],
        *,
        max_items: int = 500,
    ) -> None:
        self._store = store
        self._customer = customer_id
        self._domains = tuple(domain_ids)
        self._max_items = max_items

    async def read(self) -> GatewayRead:
        found: list[GatewayFragments] = []
        truncated = False
        try:
            for domain in self._domains:
                cursor: str | None = None
                while True:
                    page = await self._store.list(
                        self._customer, domain, cursor=cursor, limit=min(_PAGE, self._max_items)
                    )
                    for reg in page.items:
                        if len(found) >= self._max_items:
                            truncated = True
                            break
                        inv = await self._store.get_inventory(self._customer, domain, reg.id)
                        if inv is None:
                            # Registered but never inventoried: unknown, not a pass.
                            found.append(
                                GatewayFragments(
                                    reg.id,
                                    frozenset(),
                                    domain_id=domain,
                                    unreadable_lists=("policy_fragments",),
                                )
                            )
                            continue
                        found.append(
                            GatewayFragments(
                                reg.id,
                                frozenset(f.name for f in inv.policy_fragments),
                                domain_id=domain,
                                unreadable_lists=tuple(inv.unreadable_lists),
                            )
                        )
                    cursor = page.next_cursor
                    if truncated or cursor is None:
                        break
        except Exception as exc:
            logger.warning(
                "gateway inventory read failed",
                extra={
                    "event": "worker.detections_gateway_unreadable",
                    "error": type(exc).__name__,
                },
            )
            return GatewayRead(status="unreadable", reason="store_error")
        return GatewayRead(gateways=tuple(found), truncated=truncated)


class CatalogProjectReader:
    """``model_deployment`` entities' ``foundry_project`` values, via the worker's scope."""

    def __init__(
        self,
        repository: EntityLister,
        scope_provider: Callable[[], Awaitable[Any]],
        domain_ids: Sequence[str],
        *,
        max_items: int = 5000,
    ) -> None:
        self._repo = repository
        self._scope_provider = scope_provider
        self._domains = tuple(domain_ids)
        self._max_items = max_items

    async def read(self) -> CatalogRead:
        projects: set[str] = set()
        seen = 0
        try:
            scope = await self._scope_provider()
            flt = EntityFilter(entity_types=["model_deployment"], domain_ids=list(self._domains))
            cursor: str | None = None
            while True:
                page = await self._repo.list_entities(
                    scope, flt, PageRequest(page_size=_PAGE, cursor=cursor)
                )
                for entity in page.items:
                    seen += 1
                    project = _project(entity)
                    if project is not None:
                        projects.add(project)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if seen >= self._max_items:
                    return CatalogRead(projects=frozenset(projects), truncated=True)
        except Exception as exc:
            logger.warning(
                "catalog read failed",
                extra={
                    "event": "worker.detections_catalog_unreadable",
                    "error": type(exc).__name__,
                },
            )
            return CatalogRead(ok=False, reason="catalog_read_failed")
        return CatalogRead(projects=frozenset(projects))


def _project(entity: Any) -> str | None:
    root = getattr(getattr(entity, "attributes", None), "root", None)
    if not isinstance(root, dict):
        return None
    value = root.get("foundry_project")  # pyright: ignore[reportUnknownMemberType]
    return value[:256] if isinstance(value, str) and value else None


class EntityLister(Protocol):
    """The one catalog method the reader needs."""

    async def list_entities(self, scope: Any, flt: Any, page: Any) -> Any: ...


class GatewayLister(Protocol):
    """The two gateway-store methods the reader needs."""

    async def list(
        self, customer_id: str, domain_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Any: ...

    async def get_inventory(self, customer_id: str, domain_id: str, gateway_id: str) -> Any: ...
