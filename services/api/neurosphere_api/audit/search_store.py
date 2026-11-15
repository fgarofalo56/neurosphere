"""Audit search store (PRP-40 item 3, Clarification 2): filters over ONE chain at a time.

The route resolves the chains a caller may read (never a chain id from the caller) and asks this
store for each one. Two implementations:

* :class:`CosmosAuditSearchStore` -- a parameterized, single-partition query per chain over the
  ``audit`` container the audit store writes (documents are ``AuditRecord`` JSON plus ``id`` and
  ``doc_type``; see ``neurosphere_core.audit.cosmos_store``). It reads the container itself and
  never edits the chain store. No caller text reaches the query: only fixed clause text and
  ``@`` parameters are interpolated.
* :class:`RepositoryAuditSearchStore` -- the in-memory twin: pages backwards through any
  ``AuditRepository`` (used with the in-memory audit store in tests and the local sandbox).

Order is newest first by ``(recorded_at, chain_id, sequence)``. Within one chain ``recorded_at``
never decreases with ``sequence`` (the repository stamps at append under the chain's lock), so a
chain is read by ``sequence DESC`` and the position key is exact. :class:`SearchPosition` is the
cursor content; the route encodes it opaquely.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.chain import format_timestamp
from neurosphere_core.audit.repository import MAX_RANGE
from neurosphere_core.audit.store import RECORD_DOC_TYPE
from neurosphere_core.errors import DependencyTransientError
from pydantic import ValidationError

__all__ = [
    "MAX_SCAN_PER_CHAIN",
    "AuditSearchFilter",
    "AuditSearchStore",
    "CosmosAuditSearchStore",
    "RepositoryAuditSearchStore",
    "SearchPosition",
    "position_of",
]

#: Upper bound of records the in-memory twin inspects per chain per call (bounded work).
MAX_SCAN_PER_CHAIN: Final = 20_000

Kind = Literal["before", "after", "denied"]
Result = Literal["succeeded", "failed", "rolled_back"]


@dataclass(frozen=True, slots=True)
class AuditSearchFilter:
    """Validated filters (the route checks every pattern before this is built)."""

    since: datetime
    until: datetime
    operation: str | None = None
    kind: Kind | None = None
    outcome: Result | None = None
    actor: str | None = None
    correlation_id: str | None = None

    def matches(self, record: AuditRecord) -> bool:
        recorded = _recorded_at(record)
        if not format_timestamp(self.since) <= recorded < format_timestamp(self.until):
            return False
        if self.operation is not None and record.operation != self.operation:
            return False
        if self.kind is not None and record.kind != self.kind:
            return False
        if self.outcome is not None and (
            record.outcome is None or record.outcome.result != self.outcome
        ):
            return False
        if self.actor is not None and record.actor.principal_pseudonym != self.actor:
            return False
        return self.correlation_id is None or record.correlation_id == self.correlation_id


@dataclass(frozen=True, slots=True, order=True)
class SearchPosition:
    """Sort key of a record: ``(recorded_at, chain_id, sequence)``; larger is newer."""

    recorded_at: str
    chain_id: str
    sequence: int


def _recorded_at(record: AuditRecord) -> str:
    """Contract ``UtcTimestamp`` text; the repository always writes microsecond precision, so
    lexical order is time order."""
    return record.recorded_at.root


def position_of(record: AuditRecord) -> SearchPosition:
    return SearchPosition(_recorded_at(record), record.chain_id, record.sequence)


@runtime_checkable
class AuditSearchStore(Protocol):
    async def search(
        self,
        chain_id: str,
        flt: AuditSearchFilter,
        *,
        before: SearchPosition | None,
        limit: int,
    ) -> list[AuditRecord]:
        """Up to ``limit`` matching records of ``chain_id`` older than ``before``, newest first."""
        ...


def _older(record: AuditRecord, before: SearchPosition | None) -> bool:
    return before is None or position_of(record) < before


class RepositoryAuditSearchStore:
    """In-memory twin over an ``AuditRepository`` (pages backwards from the tail)."""

    def __init__(self, repository: AuditRepository, *, max_scan: int = MAX_SCAN_PER_CHAIN) -> None:
        self._repository = repository
        self._max_scan = max_scan

    async def _newest_first(self, chain_id: str) -> AsyncIterator[AuditRecord]:
        tail = await self._repository.tail(chain_id)
        if tail is None:
            return
        stop = tail.sequence + 1
        scanned = 0
        while stop > 0 and scanned < self._max_scan:
            start = max(0, stop - MAX_RANGE)
            batch = await self._repository.read_range(chain_id, start=start, limit=stop - start)
            for record in reversed(batch):
                yield record
            scanned += stop - start
            stop = start

    async def search(
        self,
        chain_id: str,
        flt: AuditSearchFilter,
        *,
        before: SearchPosition | None,
        limit: int,
    ) -> list[AuditRecord]:
        found: list[AuditRecord] = []
        since = format_timestamp(flt.since)
        async for record in self._newest_first(chain_id):
            if _recorded_at(record) < since:
                break  # older records only from here on
            if _older(record, before) and flt.matches(record):
                found.append(record)
                if len(found) >= limit:
                    break
        return found


class CosmosAuditSearchStore:
    """Parameterized single-partition queries over the ``audit`` container (one per chain)."""

    def __init__(self, container: Any) -> None:
        self._container = container

    @classmethod
    def from_client(cls, client: Any, *, database: str, container: str) -> CosmosAuditSearchStore:
        return cls(client.get_database_client(database).get_container_client(container))

    @staticmethod
    def build_query(
        chain_id: str, flt: AuditSearchFilter, before: SearchPosition | None, limit: int
    ) -> tuple[str, list[dict[str, Any]]]:
        """SQL text and parameters. Only fixed clause text is concatenated (no caller input)."""
        clauses = [
            "c.doc_type = @doc_type",
            "c.recorded_at >= @since",
            "c.recorded_at < @until",
        ]
        params: list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@doc_type", "value": RECORD_DOC_TYPE},
            {"name": "@since", "value": format_timestamp(flt.since)},
            {"name": "@until", "value": format_timestamp(flt.until)},
        ]
        optional: Sequence[tuple[str, str, str | None]] = (
            ("c.operation = @operation", "@operation", flt.operation),
            ("c.kind = @kind", "@kind", flt.kind),
            ("c.outcome.result = @outcome", "@outcome", flt.outcome),
            ("c.actor.principal_pseudonym = @actor", "@actor", flt.actor),
            ("c.correlation_id = @correlation_id", "@correlation_id", flt.correlation_id),
        )
        for clause, name, value in optional:
            if value is not None:
                clauses.append(clause)
                params.append({"name": name, "value": value})
        if before is not None:
            params.append({"name": "@before_at", "value": before.recorded_at})
            if before.chain_id == chain_id:
                clauses.append(
                    "(c.recorded_at < @before_at OR "
                    "(c.recorded_at = @before_at AND c.sequence < @before_seq))"
                )
                params.append({"name": "@before_seq", "value": before.sequence})
            elif chain_id < before.chain_id:
                clauses.append("c.recorded_at <= @before_at")
            else:
                clauses.append("c.recorded_at < @before_at")
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608 - fixed clause text only
            + " AND ".join(clauses)
            + " ORDER BY c.sequence DESC"
        )
        return sql, params

    async def search(
        self,
        chain_id: str,
        flt: AuditSearchFilter,
        *,
        before: SearchPosition | None,
        limit: int,
    ) -> list[AuditRecord]:
        sql, params = self.build_query(chain_id, flt, before, limit)
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=chain_id
                )
            ]
        except Exception as exc:
            raise DependencyTransientError(
                "audit search store unavailable", reason="audit_search_unavailable"
            ) from exc
        try:
            records = [
                AuditRecord.model_validate(
                    {k: v for k, v in row.items() if not k.startswith("_") and k not in _STORAGE}
                )
                for row in rows
            ]
        except ValidationError as exc:
            raise DependencyTransientError(
                "stored audit record failed validation",
                reason="audit_record_invalid",
                upstream_invalid=True,
            ) from exc
        return records


#: Storage-only fields stripped (with Cosmos ``_`` system fields) before validation.
_STORAGE: Final = frozenset({"id", "doc_type"})
