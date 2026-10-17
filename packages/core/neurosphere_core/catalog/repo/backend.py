"""Storage seam under the catalog repository engine (PRP-10 item 1).

The engine (``engine.CatalogEngine``) holds every rule: scope checks, ETag concurrency, alias
uniqueness, evidence append-only, the Auditor gate. It talks to storage only through the tiny
structured ``Query`` below, so the Cosmos backend (parameterized SQL) and the in-memory backend
(a Python evaluator) cannot disagree about scope filtering: both get their scope predicate
from the same ``ScopeFilter`` value.

``Query`` is deliberately not a query language. Field names come from the ``Field`` allowlist
(never from callers) and every value travels as a parameter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args

DocType = Literal["entity", "edge", "observation", "override", "alias"]

Field = Literal[
    "ref",
    "entity_type",
    "lifecycle_status",
    "relation_type",
    "edge_status",
    "source_ref",
    "target_ref",
    "edge_ref",
    "alias_source_id",
    "alias_kind",
    "alias_value",
    "alias_status",
    "sort_key",
]
FIELDS: frozenset[str] = frozenset(get_args(Field))

MAX_QUERY_LIMIT = 100_000
"""Hard ceiling for any single backend query (the bounded batch of overrides)."""


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    """The server-side scope predicate. ``domains=None`` disables the domain clause and is used
    only by the engine's internal uniqueness checks; it is never derived from caller input.
    """

    cloud: str
    customer_id: str
    domains: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class Query:
    """One bounded, parameterized read: ``doc_type`` + scope + allowlisted predicates."""

    doc_type: DocType
    scope: ScopeFilter
    limit: int
    eq: tuple[tuple[Field, str], ...] = ()
    any_of: tuple[tuple[Field, tuple[str, ...]], ...] = ()
    either: tuple[tuple[Field, str], ...] = ()
    """OR group: at least one ``field == value`` pair must hold."""
    order: Field | None = None
    descending: bool = False
    after: str | None = None
    """Keyset: only rows strictly after this ``order`` value (before it when descending)."""

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_QUERY_LIMIT:
            raise ValueError(f"limit must be in 1..{MAX_QUERY_LIMIT}")
        names = [f for f, _ in self.eq] + [f for f, _ in self.any_of] + [f for f, _ in self.either]
        if self.order is not None:
            names.append(self.order)
        for name in names:
            if name not in FIELDS:
                raise ValueError(f"field {name!r} is not allowlisted")
        if self.after is not None and self.order is None:
            raise ValueError("after requires order")


class DocConflictError(Exception):
    """Insert hit an existing document (same ID in the same partition)."""


class DocPreconditionFailedError(Exception):
    """Replace lost the race: the stored document's ``_etag`` no longer matches ``if_match``."""


class DocBackend(Protocol):
    """Document storage used by the engine. Documents are plain JSON-able dicts."""

    async def query(self, query: Query) -> Sequence[dict[str, Any]]:
        """Matching documents (each carrying its storage ``_etag``), ordered and limited."""
        ...

    async def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Create ``doc``; raises ``DocConflictError`` when the ID exists in its partition."""
        ...

    async def replace(self, doc: dict[str, Any], if_match: str) -> dict[str, Any]:
        """Replace ``doc`` iff the stored ``_etag`` equals ``if_match``, else
        ``DocPreconditionFailedError``.
        """
        ...
