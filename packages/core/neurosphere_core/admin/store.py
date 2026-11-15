"""Versioned, ETag-guarded operator configuration store (``admin_config``) and its in-memory twin.

One :class:`AdminConfigDocument` per ``(customer_id, kind, id)``. Rules every implementation
shares (they live in :class:`AdminConfigStoreBase`, so the twins cannot drift):

* ``create`` writes ``version`` 1, ``status`` ``active``; an existing ``(kind, id)`` (active or
  retired) is ``stale_version`` (``admin_config_exists``): ids are never reused.
* ``replace`` and ``retire`` need ``if_match`` equal to the stored ETag (else ``stale_version``,
  ``admin_config_modified``), bump ``version`` by exactly one and stamp ``updated_at`` and
  ``updated_by``. A missing document is ``not_found``.
* ``retire`` keeps the document readable (``status`` ``retired``) for audit; a retired document is
  never replaced or retired again (``stale_version``, ``admin_config_retired``) and
  ``list_by_kind`` omits it unless asked.
* Every body is validated by kind (:func:`~neurosphere_core.admin.models.validate_admin_body`)
  before anything is written: a failure is ``invalid_schema`` and nothing is stored.
* ``updated_by`` is a pseudonymous principal id of the same customer (never a UPN or email).

The caller (PRP-41/42/44/45 routes) authorizes the write and appends the audit record on
:func:`~neurosphere_core.admin.chains.admin_config_chain_id`. Nothing here logs: bodies may hold
secret URIs, hashes and tag values, which never reach a log line (#190 item 3).
"""

from __future__ import annotations

import builtins
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import count
from typing import Any, Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.common import PrincipalId
from pydantic import BaseModel, ValidationError

from neurosphere_core.admin.models import (
    ADMIN_CONFIG_SCHEMA_VERSION,
    AdminBody,
    CloudName,
    validate_admin_body,
    validate_kind,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
    ValidationIssue,
)

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "AdminConfigRepository",
    "AdminConfigStoreBase",
    "InMemoryAdminConfigRepository",
    "admin_config_exists",
    "admin_config_modified",
    "admin_config_retired",
    "admin_config_unavailable",
]

DEFAULT_LIST_LIMIT: Final = 200
MAX_LIST_LIMIT: Final = 1000
_RECORD_ID: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CUSTOMER_ID: Final = re.compile(r"^[a-z0-9._-]{1,128}$")
Clock = Callable[[], datetime]
Status = Literal["active", "retired"]


def admin_config_exists() -> StaleVersionError:
    return StaleVersionError("configuration already exists", reason="admin_config_exists")


def admin_config_modified() -> StaleVersionError:
    return StaleVersionError(
        "configuration changed since it was read", reason="admin_config_modified"
    )


def admin_config_retired() -> StaleVersionError:
    return StaleVersionError("configuration is retired", reason="admin_config_retired")


def admin_config_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "admin configuration store unavailable", reason="admin_config_unavailable"
    )


def _not_found() -> NotFoundError:
    return NotFoundError("no such configuration", reason="admin_config_not_found")


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "admin configuration request is invalid",
        errors=[ValidationIssue(pointer, detail)],
        reason=reason,
    )


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise _issue("/limit", f"limit must be 1..{MAX_LIST_LIMIT}", "limit_out_of_range")
    return limit


def _check_customer(customer_id: str) -> None:
    if not _CUSTOMER_ID.fullmatch(customer_id):
        raise _issue("/customer_id", "not a customer id", "admin_config_invalid")


def _check_ids(customer_id: str, config_id: str) -> None:
    _check_customer(customer_id)
    if not _RECORD_ID.fullmatch(config_id):
        raise _issue("/id", "not a record id", "admin_config_invalid")


def _check_actor(customer_id: str, updated_by: str) -> str:
    try:
        PrincipalId.model_validate(updated_by)
    except ValidationError as exc:
        raise _issue(
            "/updated_by", "not a pseudonymous principal id", "admin_config_invalid"
        ) from exc
    if updated_by.split(":")[1] != customer_id:
        raise _issue("/updated_by", "principal of another customer", "cross_customer")
    return updated_by


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class AdminConfigRepository(Protocol):
    """Operator configuration store. ``customer_id`` comes from the server-derived scope."""

    async def create(
        self,
        customer_id: str,
        kind: str,
        config_id: str,
        body: Mapping[str, Any] | BaseModel,
        *,
        updated_by: str,
    ) -> AdminConfigDocument: ...

    async def get(
        self, customer_id: str, kind: str, config_id: str
    ) -> AdminConfigDocument | None: ...

    async def list_by_kind(
        self,
        customer_id: str,
        kind: str,
        *,
        include_retired: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> builtins.list[AdminConfigDocument]: ...

    async def replace(
        self,
        customer_id: str,
        kind: str,
        config_id: str,
        body: Mapping[str, Any] | BaseModel,
        *,
        if_match: str,
        updated_by: str,
    ) -> AdminConfigDocument: ...

    async def retire(
        self, customer_id: str, kind: str, config_id: str, *, if_match: str, updated_by: str
    ) -> AdminConfigDocument: ...


class AdminConfigStoreBase(ABC):
    """Shared validation, versioning and precondition rules over four storage primitives."""

    def __init__(self, *, cloud: CloudName | None = None, clock: Clock | None = None) -> None:
        self._cloud: CloudName | None = cloud
        self._clock: Clock = clock or _utc_now

    # -- storage primitives ------------------------------------------------------------------

    @abstractmethod
    async def _read(
        self, customer_id: str, kind: str, config_id: str
    ) -> AdminConfigDocument | None: ...

    @abstractmethod
    async def _insert(self, document: AdminConfigDocument) -> AdminConfigDocument:
        """Create-only write; an existing id raises :func:`admin_config_exists`."""

    @abstractmethod
    async def _replace(
        self, document: AdminConfigDocument, *, if_match: str
    ) -> AdminConfigDocument:
        """Write under ``if_match``; a mismatch raises :func:`admin_config_modified`."""

    @abstractmethod
    async def _scan(
        self, customer_id: str, kind: str, *, include_retired: bool, limit: int
    ) -> builtins.list[AdminConfigDocument]: ...

    # -- public API ----------------------------------------------------------------------------

    def _envelope(
        self,
        customer_id: str,
        kind: str,
        config_id: str,
        body: AdminBody,
        *,
        version: int,
        status: Status,
        updated_by: str,
        etag: str,
    ) -> AdminConfigDocument:
        return AdminConfigDocument.model_validate(
            {
                "schema_version": ADMIN_CONFIG_SCHEMA_VERSION,
                "id": config_id,
                "customer_id": customer_id,
                "kind": kind,
                "version": version,
                "etag": etag,
                "status": status,
                "updated_at": _timestamp(self._clock()),
                "updated_by": updated_by,
                "body": body,
            }
        )

    def _body(self, kind: str, body: Mapping[str, Any] | BaseModel, customer_id: str) -> AdminBody:
        return validate_admin_body(kind, body, customer_id=customer_id, cloud=self._cloud)

    async def create(
        self,
        customer_id: str,
        kind: str,
        config_id: str,
        body: Mapping[str, Any] | BaseModel,
        *,
        updated_by: str,
    ) -> AdminConfigDocument:
        validate_kind(kind)
        _check_ids(customer_id, config_id)
        actor = _check_actor(customer_id, updated_by)
        model = self._body(kind, body, customer_id)
        document = self._envelope(
            customer_id,
            kind,
            config_id,
            model,
            version=1,
            status="active",
            updated_by=actor,
            etag="pending",
        )
        return await self._insert(document)

    async def get(self, customer_id: str, kind: str, config_id: str) -> AdminConfigDocument | None:
        validate_kind(kind)
        _check_ids(customer_id, config_id)
        return await self._read(customer_id, kind, config_id)

    async def list_by_kind(
        self,
        customer_id: str,
        kind: str,
        *,
        include_retired: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> builtins.list[AdminConfigDocument]:
        validate_kind(kind)
        _check_customer(customer_id)
        return await self._scan(
            customer_id, kind, include_retired=include_retired, limit=check_limit(limit)
        )

    async def _current(
        self, customer_id: str, kind: str, config_id: str, if_match: str
    ) -> AdminConfigDocument:
        current = await self._read(customer_id, kind, config_id)
        if current is None:
            raise _not_found()
        if current.status == "retired":
            raise admin_config_retired()
        if current.etag.root != if_match:
            raise admin_config_modified()
        return current

    async def replace(
        self,
        customer_id: str,
        kind: str,
        config_id: str,
        body: Mapping[str, Any] | BaseModel,
        *,
        if_match: str,
        updated_by: str,
    ) -> AdminConfigDocument:
        validate_kind(kind)
        _check_ids(customer_id, config_id)
        actor = _check_actor(customer_id, updated_by)
        model = self._body(kind, body, customer_id)
        current = await self._current(customer_id, kind, config_id, if_match)
        document = self._envelope(
            customer_id,
            kind,
            config_id,
            model,
            version=current.version.root + 1,
            status="active",
            updated_by=actor,
            etag=if_match,
        )
        return await self._replace(document, if_match=if_match)

    async def retire(
        self, customer_id: str, kind: str, config_id: str, *, if_match: str, updated_by: str
    ) -> AdminConfigDocument:
        validate_kind(kind)
        _check_ids(customer_id, config_id)
        actor = _check_actor(customer_id, updated_by)
        current = await self._current(customer_id, kind, config_id, if_match)
        document = self._envelope(
            customer_id,
            kind,
            config_id,
            current.body,
            version=current.version.root + 1,
            status="retired",
            updated_by=actor,
            etag=if_match,
        )
        return await self._replace(document, if_match=if_match)


class InMemoryAdminConfigRepository(AdminConfigStoreBase):
    """Twin of :class:`~neurosphere_core.admin.cosmos_store.CosmosAdminConfigRepository` for tests
    and the local sandbox. Never a production store."""

    def __init__(
        self,
        *,
        cloud: CloudName | None = None,
        clock: Clock | None = None,
        etag_factory: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(cloud=cloud, clock=clock)
        self._docs: dict[tuple[str, str, str], AdminConfigDocument] = {}
        counter = count(1)
        self._next_etag = etag_factory or (lambda: f'"cfg-{next(counter)}"')
        self.error: BaseException | None = None

    def fail_with(self, error: BaseException | None) -> None:
        """Make every storage call raise ``error`` (outage simulation)."""
        self.error = error

    def _guard(self) -> None:
        if self.error is not None:
            raise self.error

    @staticmethod
    def _key(document: AdminConfigDocument) -> tuple[str, str, str]:
        return document.customer_id.root, document.kind.root, document.id.root

    def _stamp(self, document: AdminConfigDocument) -> AdminConfigDocument:
        stored = document.model_copy(update={"etag": type(document.etag)(self._next_etag())})
        self._docs[self._key(stored)] = stored
        return stored

    async def _read(
        self, customer_id: str, kind: str, config_id: str
    ) -> AdminConfigDocument | None:
        self._guard()
        return self._docs.get((customer_id, kind, config_id))

    async def _insert(self, document: AdminConfigDocument) -> AdminConfigDocument:
        self._guard()
        if self._key(document) in self._docs:
            raise admin_config_exists()
        return self._stamp(document)

    async def _replace(
        self, document: AdminConfigDocument, *, if_match: str
    ) -> AdminConfigDocument:
        self._guard()
        current = self._docs.get(self._key(document))
        if current is None or current.etag.root != if_match:
            raise admin_config_modified()
        return self._stamp(document)

    async def _scan(
        self, customer_id: str, kind: str, *, include_retired: bool, limit: int
    ) -> builtins.list[AdminConfigDocument]:
        self._guard()
        docs = [
            d
            for (cust, k, _), d in self._docs.items()
            if cust == customer_id and k == kind and (include_retired or d.status == "active")
        ]
        docs.sort(key=lambda d: d.id.root)
        return docs[:limit]
