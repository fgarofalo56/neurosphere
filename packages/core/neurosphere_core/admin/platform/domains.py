"""Domain registry administration over the ``admin_config`` store (PRP-44 item 1).

A domain is an ``admin_config`` document of kind ``domain`` whose id is the canonical domain id.
Rules, in addition to the contract and the PRP-65 core rules (``validate_admin_body``):

* the id is canonical for the deployment cloud and the caller's customer (never taken from a
  body that names another customer or cloud);
* the reserved ``customer-control`` domain carries ``is_control_domain`` true, and no other
  domain may; the control domain can never be retired;
* a domain name that would collide with a customer-wide audit chain name is refused;
* the control domain is registered first when a first ordinary domain is created;
* a retired domain keeps its record (the store never deletes), is not "registered" any more, and
  its id is never reused.

:class:`DomainRegistry` answers "is this domain registered" straight from the store (no cache:
every replica sees the same answer). It enforces only once the registry is non-empty, so an
existing deployment keeps working until it registers domains (clarification 5).

Nothing here logs.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition

from neurosphere_core.admin.models import CloudName
from neurosphere_core.admin.store import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.auth.scope.permissions import customer_control_domain_id
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError, ValidationIssue

__all__ = [
    "DOMAIN_KIND",
    "RESERVED_DOMAIN_NAMES",
    "DomainAdmin",
    "DomainRegistry",
    "DomainWrite",
]

DOMAIN_KIND: Final = "domain"
#: Names the customer-wide audit chains use (``<customer>.<name>``); a domain of this name would
#: decode to the same chain id (see ``neurosphere_core.admin.chains``).
RESERVED_DOMAIN_NAMES: Final = frozenset({"admin-config", "gateway", "execution-control"})
_CANONICAL_PARTS: Final = 5


@dataclass(frozen=True, slots=True)
class DomainWrite:
    """An accepted domain write: the stored document and whether the control domain was added."""

    document: AdminConfigDocument
    control_registered: bool = False


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "domain definition is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _parts(domain_id: str) -> list[str]:
    return domain_id.split(":")


def _name_of(domain_id: str) -> str:
    return _parts(domain_id)[-1]


def _check_canonical(domain_id: str, customer_id: str, cloud: CloudName) -> None:
    parts = _parts(domain_id)
    if len(parts) != _CANONICAL_PARTS or parts[3] != "domain":
        raise _issue("/domain_id", "not a canonical domain id", "domain_id_not_canonical")
    if parts[0] != cloud:
        raise _issue("/domain_id", "domain belongs to another cloud", "cross_cloud")
    if parts[1] != customer_id:
        raise _issue("/domain_id", "domain belongs to another customer", "cross_customer")


class DomainRegistry:
    """Read side: which domains of a customer are registered (active)."""

    def __init__(self, repository: AdminConfigRepository) -> None:
        self._repository = repository

    async def _all(self, customer_id: str, *, include_retired: bool) -> list[AdminConfigDocument]:
        return await self._repository.list_by_kind(
            customer_id, DOMAIN_KIND, include_retired=include_retired, limit=MAX_LIST_LIMIT
        )

    async def has_any(self, customer_id: str) -> bool:
        """True once the customer registered at least one domain (retired ones count)."""
        return bool(await self._all(customer_id, include_retired=True))

    async def is_registered(self, customer_id: str, domain_id: str) -> bool:
        """True when ``domain_id`` is registered and not retired."""
        document = await self._repository.get(customer_id, DOMAIN_KIND, domain_id)
        return document is not None and document.status == "active"

    async def unregistered(self, customer_id: str, domain_ids: builtins.list[str]) -> list[str]:
        """The ids in ``domain_ids`` that violate the registry; empty while the registry is.

        Order is preserved and duplicates are reported once.
        """
        if not domain_ids or not await self.has_any(customer_id):
            return []
        missing: list[str] = []
        for domain_id in dict.fromkeys(domain_ids):
            if not await self.is_registered(customer_id, domain_id):
                missing.append(domain_id)
        return missing


class DomainAdmin:
    """Create, retire, get and list domains."""

    def __init__(self, repository: AdminConfigRepository, *, cloud: CloudName) -> None:
        self._repository = repository
        self._cloud: CloudName = cloud

    def _check(self, customer_id: str, body: DomainDefinition) -> None:
        domain_id = body.domain_id.root
        _check_canonical(domain_id, customer_id, self._cloud)
        control = customer_control_domain_id(self._cloud, customer_id)
        is_control = domain_id == control
        if is_control != body.is_control_domain:
            raise _issue(
                "/is_control_domain",
                "only the reserved customer-control domain is the control domain",
                "control_domain_flag_mismatch",
            )
        name = _name_of(domain_id)
        if name in RESERVED_DOMAIN_NAMES:
            raise _issue("/domain_id", "domain name is reserved", "reserved_domain_name")
        if body.status != "active":
            raise _issue("/status", "a new domain is created active", "domain_status_invalid")

    def _control_body(self, customer_id: str, like: DomainDefinition) -> DomainDefinition:
        return DomainDefinition.model_validate(
            {
                "schema_version": like.schema_version.root,
                "domain_id": customer_control_domain_id(self._cloud, customer_id),
                "display_name": "Customer control",
                "classification": "internal",
                "residency_region": like.residency_region,
                "status": "active",
                "is_control_domain": True,
            }
        )

    async def create(
        self, customer_id: str, body: DomainDefinition, *, updated_by: str
    ) -> DomainWrite:
        self._check(customer_id, body)
        control_registered = False
        if not body.is_control_domain:
            control_id = customer_control_domain_id(self._cloud, customer_id)
            if await self._repository.get(customer_id, DOMAIN_KIND, control_id) is None:
                await self._repository.create(
                    customer_id,
                    DOMAIN_KIND,
                    control_id,
                    self._control_body(customer_id, body),
                    updated_by=updated_by,
                )
                control_registered = True
        document = await self._repository.create(
            customer_id, DOMAIN_KIND, body.domain_id.root, body, updated_by=updated_by
        )
        return DomainWrite(document, control_registered)

    async def retire(
        self, customer_id: str, domain_id: str, *, if_match: str, updated_by: str
    ) -> AdminConfigDocument:
        _check_canonical(domain_id, customer_id, self._cloud)
        if domain_id == customer_control_domain_id(self._cloud, customer_id):
            raise StaleVersionError(
                "the control domain cannot be retired", reason="control_domain_protected"
            )
        return await self._repository.retire(
            customer_id, DOMAIN_KIND, domain_id, if_match=if_match, updated_by=updated_by
        )

    async def get(self, customer_id: str, domain_id: str) -> AdminConfigDocument | None:
        return await self._repository.get(customer_id, DOMAIN_KIND, domain_id)

    async def list(
        self,
        customer_id: str,
        *,
        include_retired: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> builtins.list[AdminConfigDocument]:
        return await self._repository.list_by_kind(
            customer_id, DOMAIN_KIND, include_retired=include_retired, limit=limit
        )
