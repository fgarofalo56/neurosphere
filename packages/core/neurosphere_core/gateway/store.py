"""Gateway store port and the in-memory implementation (tests and the local sandbox).

Contract for every implementation (``CosmosGatewayStore`` is the durable one):

* ``create`` is create-only: a second registration of the same id raises ``stale_version`` reason
  ``gateway_already_registered``.
* ``replace`` is ETag-conditional: mismatch or vanished document raises ``stale_version`` reason
  ``gateway_modified``. It returns the registration with its NEW etag.
* ``put_inventory`` REPLACES the snapshot for the gateway (never merges).
* ``list`` pages one ``(customer_id, domain_id)`` partition, newest first, opaque cursor.
* Outages raise ``dependency_transient`` (reason ``gateway_store_unavailable``); never "empty".
"""

from __future__ import annotations

import base64
import binascii
import itertools
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
    ValidationIssue,
)
from neurosphere_core.gateway.models import GatewayInventory, GatewayRegistration
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = [
    "GATEWAY_ALREADY_REGISTERED",
    "GATEWAY_MODIFIED",
    "GATEWAY_STORE_UNAVAILABLE",
    "GatewayModeLookup",
    "GatewayStore",
    "InMemoryGatewayStore",
    "check_limit",
    "decode_cursor",
    "encode_cursor",
    "store_unavailable",
]

GATEWAY_ALREADY_REGISTERED: Final = "gateway_already_registered"
GATEWAY_MODIFIED: Final = "gateway_modified"
GATEWAY_STORE_UNAVAILABLE: Final = "gateway_store_unavailable"
_CURSOR_PREFIX: Final = "g1."


@runtime_checkable
class GatewayStore(Protocol):
    async def create(self, registration: GatewayRegistration) -> GatewayRegistration: ...

    async def get(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayRegistration | None: ...

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[GatewayRegistration]: ...

    async def replace(
        self, registration: GatewayRegistration, *, if_match: str
    ) -> GatewayRegistration: ...

    async def put_inventory(
        self, customer_id: str, domain_id: str, inventory: GatewayInventory
    ) -> None: ...

    async def get_inventory(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayInventory | None: ...


@runtime_checkable
class GatewayModeLookup(Protocol):
    """Find a registration by customer and gateway id alone (PRP-34 item 2, mode checks).

    A write connector is bound to one gateway but an action request does not carry the domain
    the gateway is registered in; gateway ids are unique per customer (the id hashes the domain).
    """

    async def find(self, customer_id: str, gateway_id: str) -> GatewayRegistration | None: ...


def store_unavailable() -> DependencyTransientError:
    return DependencyTransientError("gateway store unavailable", reason=GATEWAY_STORE_UNAVAILABLE)


def already_registered() -> StaleVersionError:
    return StaleVersionError(
        "gateway is already registered in this domain", reason=GATEWAY_ALREADY_REGISTERED
    )


def modified() -> StaleVersionError:
    return StaleVersionError("gateway was modified concurrently", reason=GATEWAY_MODIFIED)


def _bad_cursor() -> InvalidSchemaError:
    return InvalidSchemaError(
        "cursor is not valid", errors=[ValidationIssue("/cursor", "cursor is not valid")]
    )


def encode_cursor(key: str) -> str:
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    if not cursor.startswith(_CURSOR_PREFIX):
        raise _bad_cursor()
    try:
        return base64.urlsafe_b64decode(cursor[len(_CURSOR_PREFIX) :].encode("ascii")).decode(
            "utf-8"
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise _bad_cursor() from exc


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidSchemaError(
            f"limit must be 1..{MAX_PAGE_SIZE}",
            errors=[ValidationIssue("/limit", f"limit must be 1..{MAX_PAGE_SIZE}")],
        )
    return limit


class InMemoryGatewayStore:
    """Per-process store. Never a production store. ``fail_with`` simulates an outage.

    Documents are kept serialized and re-validated on every read, like a durable store.
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str, str], tuple[dict[str, Any], str]] = {}
        self._inventory: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._etags = itertools.count(1)
        self.error: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    def _load(self, key: tuple[str, str, str]) -> GatewayRegistration | None:
        found = self._docs.get(key)
        if found is None:
            return None
        document, etag = found
        return GatewayRegistration.model_validate({**document, "etag": etag})

    def _put(self, registration: GatewayRegistration) -> GatewayRegistration:
        key = (registration.customer_id, registration.domain_id, registration.id)
        etag = f'"{next(self._etags)}"'
        self._docs[key] = (registration.model_dump(mode="json", exclude={"etag"}), etag)
        loaded = self._load(key)
        assert loaded is not None
        return loaded

    async def create(self, registration: GatewayRegistration) -> GatewayRegistration:
        self._check()
        key = (registration.customer_id, registration.domain_id, registration.id)
        if key in self._docs:
            raise already_registered()
        return self._put(registration)

    async def get(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayRegistration | None:
        self._check()
        return self._load((customer_id, domain_id, gateway_id))

    async def find(self, customer_id: str, gateway_id: str) -> GatewayRegistration | None:
        self._check()
        for key in list(self._docs):
            if key[0] == customer_id and key[2] == gateway_id:
                return self._load(key)
        return None

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[GatewayRegistration]:
        self._check()
        check_limit(limit)
        after = decode_cursor(cursor) if cursor is not None else None
        rows = [
            r
            for key in list(self._docs)
            if key[0] == customer_id and key[1] == domain_id and (r := self._load(key)) is not None
        ]
        rows.sort(key=lambda r: r.sort_key(), reverse=True)
        if after is not None:
            rows = [r for r in rows if r.sort_key() < after]
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].sort_key()) if len(rows) > limit else None
        return Page[GatewayRegistration](items=tuple(page), next_cursor=next_cursor)

    async def replace(
        self, registration: GatewayRegistration, *, if_match: str
    ) -> GatewayRegistration:
        self._check()
        key = (registration.customer_id, registration.domain_id, registration.id)
        current = self._docs.get(key)
        if current is None or current[1] != if_match:
            raise modified()
        return self._put(registration)

    async def put_inventory(
        self, customer_id: str, domain_id: str, inventory: GatewayInventory
    ) -> None:
        self._check()
        self._inventory[(customer_id, domain_id, inventory.gateway_id)] = inventory.model_dump(
            mode="json"
        )

    async def get_inventory(
        self, customer_id: str, domain_id: str, gateway_id: str
    ) -> GatewayInventory | None:
        self._check()
        found = self._inventory.get((customer_id, domain_id, gateway_id))
        return None if found is None else GatewayInventory.model_validate(found)
