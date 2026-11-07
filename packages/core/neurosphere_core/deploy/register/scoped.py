"""Customer-scoped view of a register store (PRP-08 item 14).

The register is partitioned by deployment id, not by customer, so a caller who knows (or guesses)
another customer's deployment id could otherwise read its resource ids.
:class:`CustomerScopedRegister` wraps any :class:`RegisterStore` for exactly one customer:

* reads return only rows whose ``customer_id`` equals the bound customer; rows with no customer
  (written before the field existed) and other customers' rows are invisible, so an unknown
  deployment and another customer's deployment look identical (no existence leak);
* writes stamp the bound customer on the row, and refuse to overwrite a row that belongs to
  another customer or to nobody (``ForbiddenError`` ``register_row_not_owned``);
* consents are not exposed across customers: they are listed only for deployments that have at
  least one visible row.
"""

from __future__ import annotations

from typing import Final

from neurosphere_core.deploy.register.models import ConsentRecord, ResourceRow
from neurosphere_core.deploy.register.store import RegisterStore
from neurosphere_core.errors import ForbiddenError

__all__ = ["CustomerScopedRegister"]

_NOT_OWNED: Final = "register_row_not_owned"


class CustomerScopedRegister:
    """A :class:`RegisterStore` bound to one customer (fail closed)."""

    def __init__(self, inner: RegisterStore, customer_id: str) -> None:
        if not customer_id:
            raise ValueError("a customer id is required")
        self._inner = inner
        self._customer = customer_id

    @property
    def customer_id(self) -> str:
        return self._customer

    def _mine(self, row: ResourceRow | None) -> ResourceRow | None:
        return row if row is not None and row.customer_id == self._customer else None

    async def put_row(self, row: ResourceRow) -> None:
        if row.customer_id not in (None, self._customer):
            raise ForbiddenError("the register row belongs to another customer", reason=_NOT_OWNED)
        existing = await self._inner.get_row(row.deployment_id, row.resource_id)
        if existing is not None and existing.customer_id != self._customer:
            raise ForbiddenError("the register row belongs to another customer", reason=_NOT_OWNED)
        await self._inner.put_row(row.model_copy(update={"customer_id": self._customer}))

    async def get_row(self, deployment_id: str, resource_id: str) -> ResourceRow | None:
        return self._mine(await self._inner.get_row(deployment_id, resource_id))

    async def list_rows(self, deployment_id: str) -> list[ResourceRow]:
        return [r for r in await self._inner.list_rows(deployment_id) if self._mine(r) is not None]

    async def put_consent(self, consent: ConsentRecord) -> None:
        if not await self.list_rows(consent.deployment_id):
            raise ForbiddenError("the deployment is not known to this customer", reason=_NOT_OWNED)
        await self._inner.put_consent(consent)

    async def list_consents(self, deployment_id: str) -> list[ConsentRecord]:
        if not await self.list_rows(deployment_id):
            return []
        return await self._inner.list_consents(deployment_id)
