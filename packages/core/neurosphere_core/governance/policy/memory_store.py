"""In-memory policy engine stores (tests and ``NS_ENV=local``; never a production store).

The store logic is the shared ``Document*Store`` code in :mod:`.store`; this module only supplies
:class:`InMemoryDocumentBackend`, a dict with the Cosmos semantics the stores rely on: per
partition ``(customer_id, domain_id)`` ids, create-only creates, ETag-checked replaces, and
structured queries ordered by ``sort_key`` over the same closed field list the Cosmos backend
accepts. Bindings use :class:`~neurosphere_core.admin.store.InMemoryAdminConfigRepository`.
"""

from __future__ import annotations

import builtins
import copy
import itertools
from collections.abc import Mapping
from typing import Any

from neurosphere_core.admin.models import CloudName
from neurosphere_core.admin.store import InMemoryAdminConfigRepository
from neurosphere_core.governance.policy.store import (
    BindingStore,
    DocumentConflictError,
    DocumentEvaluationStatusStore,
    DocumentExceptionStore,
    DocumentExistsError,
    DocumentPolicyDefinitionStore,
    DocumentQuery,
    DocumentViolationStore,
)

__all__ = [
    "InMemoryBindingStore",
    "InMemoryDocumentBackend",
    "InMemoryEvaluationStatusStore",
    "InMemoryExceptionStore",
    "InMemoryPolicyDefinitionStore",
    "InMemoryViolationStore",
]

_Key = tuple[str, str, str]


class InMemoryDocumentBackend:
    """:class:`~.store.DocumentBackend` in a dict keyed by (customer, domain, id)."""

    def __init__(self) -> None:
        self._docs: dict[_Key, dict[str, Any]] = {}
        self._counter = itertools.count(1)
        self.error: BaseException | None = None

    def fail_with(self, error: BaseException | None) -> None:
        """Make every call raise ``error`` (outage simulation)."""
        self.error = error

    def _guard(self) -> None:
        if self.error is not None:
            raise self.error

    @staticmethod
    def _key(document: Mapping[str, Any]) -> _Key:
        return str(document["customer_id"]), str(document["domain_id"]), str(document["id"])

    def _stamp(self, document: Mapping[str, Any]) -> dict[str, Any]:
        stored = copy.deepcopy(dict(document))
        stored["_etag"] = f'"{next(self._counter):08x}"'
        self._docs[self._key(stored)] = stored
        return copy.deepcopy(stored)

    async def create(self, document: Mapping[str, Any]) -> dict[str, Any]:
        self._guard()
        if self._key(document) in self._docs:
            raise DocumentExistsError
        return self._stamp(document)

    async def read(self, customer_id: str, domain_id: str, doc_id: str) -> dict[str, Any] | None:
        self._guard()
        found = self._docs.get((customer_id, domain_id, doc_id))
        return None if found is None else copy.deepcopy(found)

    async def replace(self, document: Mapping[str, Any], *, if_match: str) -> dict[str, Any]:
        self._guard()
        current = self._docs.get(self._key(document))
        if current is None or current["_etag"] != if_match:
            raise DocumentConflictError
        return self._stamp(document)

    async def upsert(self, document: Mapping[str, Any]) -> dict[str, Any]:
        self._guard()
        return self._stamp(document)

    async def query(self, query: DocumentQuery) -> builtins.list[dict[str, Any]]:
        self._guard()
        rows: builtins.list[dict[str, Any]] = []
        for (customer, domain, _), doc in self._docs.items():
            if customer != query.customer_id:
                continue
            if query.domain_id is not None and domain != query.domain_id:
                continue
            if any(name not in doc or doc[name] != value for name, value in query.equals):
                continue
            if any(name not in doc or doc[name] not in values for name, values in query.any_of):
                continue
            # Cosmos semantics: a missing or null field is undefined under ``!=`` (no match).
            if any(doc.get(name) is None or doc[name] == value for name, value in query.not_equals):
                continue
            key = doc.get("sort_key")
            if not isinstance(key, str):
                continue
            if query.after is not None and (
                key >= query.after if query.descending else key <= query.after
            ):
                continue
            rows.append(doc)
        rows.sort(key=lambda d: d["sort_key"], reverse=query.descending)
        return [copy.deepcopy(r) for r in rows[: query.limit]]


class InMemoryPolicyDefinitionStore(DocumentPolicyDefinitionStore):
    """Policy versions in memory. Pass ``backend`` to share it with
    :class:`InMemoryEvaluationStatusStore` (one ``policy_definitions`` container)."""

    def __init__(self, backend: InMemoryDocumentBackend | None = None) -> None:
        self.backend = backend or InMemoryDocumentBackend()
        super().__init__(self.backend)


class InMemoryEvaluationStatusStore(DocumentEvaluationStatusStore):
    def __init__(self, backend: InMemoryDocumentBackend | None = None) -> None:
        self.backend = backend or InMemoryDocumentBackend()
        super().__init__(self.backend)


class InMemoryViolationStore(DocumentViolationStore):
    def __init__(
        self,
        backend: InMemoryDocumentBackend | None = None,
        *,
        resolve_batch: int = 1000,
        resolve_max_batches: int = 50,
    ) -> None:
        self.backend = backend or InMemoryDocumentBackend()
        super().__init__(
            self.backend, resolve_batch=resolve_batch, resolve_max_batches=resolve_max_batches
        )


class InMemoryExceptionStore(DocumentExceptionStore):
    def __init__(self, backend: InMemoryDocumentBackend | None = None) -> None:
        self.backend = backend or InMemoryDocumentBackend()
        super().__init__(self.backend)


class InMemoryBindingStore(BindingStore):
    """:class:`~.store.BindingStore` over a private in-memory ``admin_config`` repository."""

    def __init__(
        self,
        repository: InMemoryAdminConfigRepository | None = None,
        *,
        cloud: CloudName | None = None,
    ) -> None:
        super().__init__(repository or InMemoryAdminConfigRepository(cloud=cloud))
