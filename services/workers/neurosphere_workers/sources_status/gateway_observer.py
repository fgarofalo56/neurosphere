"""A gateway store that remembers the poll status codes written during one tick.

``GatewayPoller`` keeps its outcome on each registration (``poll_status``) and has no
``last_status``. Wrapping the store it is given lets the run status see each tick's outcomes
without editing the poller: every call is delegated unchanged and ``replace`` also notes the
status code of the registration being written.
"""

from __future__ import annotations

import builtins

from neurosphere_core.gateway import GatewayStore
from neurosphere_core.gateway.models import GatewayInventory, GatewayRegistration
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE

__all__ = ["ObservedGatewayStore"]


class ObservedGatewayStore:
    """Delegates to ``inner``; ``drain`` returns the poll status codes seen since the last call."""

    def __init__(self, inner: GatewayStore) -> None:
        self._inner = inner
        self._seen: list[str] = []

    def drain(self) -> builtins.list[str]:
        seen, self._seen = self._seen, []
        return seen

    async def create(self, registration: GatewayRegistration) -> GatewayRegistration:
        return await self._inner.create(registration)

    async def get(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayRegistration | None:
        return await self._inner.get(customer_id, domain_id, gateway_id)

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[GatewayRegistration]:
        return await self._inner.list(customer_id, domain_id, cursor=cursor, limit=limit)

    async def replace(
        self, registration: GatewayRegistration, *, if_match: str
    ) -> GatewayRegistration:
        if registration.poll_status is not None:
            self._seen.append(registration.poll_status)
        return await self._inner.replace(registration, if_match=if_match)

    async def put_inventory(
        self, customer_id: str, domain_id: str, inventory: GatewayInventory
    ) -> None:
        await self._inner.put_inventory(customer_id, domain_id, inventory)

    async def get_inventory(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayInventory | None:
        return await self._inner.get_inventory(customer_id, domain_id, gateway_id)
