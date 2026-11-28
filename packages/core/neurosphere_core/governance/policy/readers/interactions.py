"""``InteractionFindingReaderAdapter``: PRP-105's finding port over the interaction index.

PRP-104 item 8 (clarification 10: the one binding of ``InteractionFindingReader``). The adapter
reads ONLY the metadata index through ``query_index(InteractionQuery) -> IndexPage``: the
``findings_summary`` category counts, the captured ``parts`` kinds and the interaction ids. It
never calls ``read_content``, never touches a key and never decrypts; its source protocol does
not even have a content method.

Semantics, matching how ``content_rule`` consumes the answer:

* scope: the customer is the scope's; ``domain_ids`` are intersected with
  ``scope.allowed_domains`` (anything outside is dropped, never widened);
* window: ``captured_at`` in ``[start, end)``;
* categories: one index query per (domain, category) using the index's server-side
  ``detected_category`` filter; a record contributes its ``findings_summary`` count of THAT
  category only, so a record with two listed categories is counted once per category;
* parts: the index holds per-category counts without a part, so ``parts`` (empty = any part)
  selects records whose captured ``parts`` include one of the listed kinds;
* subject: the record's ``agent_id`` (``subject_type`` ``agent``), else its ``service_id``
  (``service``), else its ``tool_id`` (``tool``), matching the catalog entity types
  ``AppliesTo.matches_unregistered`` filters on; a record with none of them is not counted;
* ``limit``: at most that many distinct subjects (subject-id order), ``truncated`` when more
  matched;
* scan bound: at most :data:`MAX_INDEX_PAGES_PER_CALL` index pages (of
  ``MAX_QUERY_PAGE_SIZE`` records) per call across all domains and categories; reaching it
  stops the scan and sets ``truncated`` (the counts are then a lower bound);
* evidence: at most :data:`MAX_INTERACTION_IDS_PER_COUNT` interaction ids per row (newest
  first as the index returns them, then sorted).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord

from neurosphere_core.governance.policy.rules.findings_port import (
    FindingCountPage,
    InteractionFindingCount,
)
from neurosphere_core.interactions.models import (
    MAX_QUERY_PAGE_SIZE,
    IndexPage,
    InteractionQuery,
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_INDEX_PAGES_PER_CALL",
    "MAX_INTERACTION_IDS_PER_COUNT",
    "IndexQueryable",
    "InteractionFindingReaderAdapter",
    "index_only_source",
]

#: Hard cap on index pages read per ``count_findings`` call (all domains and categories
#: together): 50 pages x ``MAX_QUERY_PAGE_SIZE`` (100) = at most 5,000 index records per
#: evaluation of one rule. Reaching it stops the scan and answers ``truncated=True``.
MAX_INDEX_PAGES_PER_CALL: Final = 50
#: ``InteractionFindingCount.interaction_ids`` allows at most 50 references.
MAX_INTERACTION_IDS_PER_COUNT: Final = 50

_SUBJECT_FIELDS: Final = (("agent_id", "agent"), ("service_id", "service"), ("tool_id", "tool"))


@runtime_checkable
class IndexQueryable(Protocol):
    """Answers an index query: an ``InteractionStore`` or :func:`index_only_source`."""

    async def query_index(self, query: InteractionQuery) -> IndexPage: ...


class _IndexBackendLike(Protocol):
    async def query(self, query: InteractionQuery) -> IndexPage: ...


class _IndexOnlySource:
    """``query_index`` over a bare index backend (the worker: no blob client, no key wrapper)."""

    def __init__(self, index: _IndexBackendLike) -> None:
        self._index = index

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        return await self._index.query(query)


def index_only_source(index: _IndexBackendLike) -> IndexQueryable:
    """Adapt an ``IndexBackend`` (``query``) to :class:`IndexQueryable` (``query_index``)."""
    return _IndexOnlySource(index)


@dataclass
class _Tally:
    subject_type: str
    count: int = 0
    ids: list[str] = field(default_factory=list)


def _text(value: object) -> str | None:
    """The string inside a (possibly nested) contract ``RootModel``, else ``None``."""
    for _ in range(4):  # contract ids nest at most a couple of RootModels deep
        if isinstance(value, str) or value is None:
            break
        value = getattr(value, "root", None)
    return value if isinstance(value, str) else None


def _subject(record: InteractionRecord) -> tuple[str, str] | None:
    for attr, subject_type in _SUBJECT_FIELDS:
        value = _text(getattr(record, attr, None))
        if value:
            return value, subject_type
    return None


def _has_part(record: InteractionRecord, wanted: frozenset[str]) -> bool:
    if not wanted:
        return True
    return any(_text(p.part) in wanted for p in record.parts.root)


def _category_count(record: InteractionRecord, category: str) -> int:
    return sum(
        item.count for item in record.findings_summary or () if _text(item.category) == category
    )


class InteractionFindingReaderAdapter:
    """:class:`InteractionFindingReader` over the interaction metadata index (counts and ids)."""

    def __init__(
        self, source: IndexQueryable, *, max_pages: int = MAX_INDEX_PAGES_PER_CALL
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self._source = source
        self._max_pages = max_pages

    async def count_findings(
        self,
        scope: IdentityScope,
        *,
        domain_ids: Sequence[str],
        categories: Sequence[str],
        parts: Sequence[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> FindingCountPage:
        allowed = frozenset(scope.allowed_domains)
        domains = sorted({d for d in domain_ids if d in allowed})
        wanted_categories = sorted({c for c in categories if c})
        if not domains or not wanted_categories or limit < 1 or start >= end:
            return FindingCountPage()
        wanted_parts = frozenset(parts)
        tallies: dict[tuple[str, str, str], _Tally] = {}
        pages_left = self._max_pages
        exhausted = False
        for domain_id in domains:
            for category in wanted_categories:
                continuation: str | None = None
                while True:
                    if pages_left <= 0:
                        exhausted = True
                        break
                    pages_left -= 1
                    page = await self._source.query_index(
                        InteractionQuery(
                            customer_id=scope.customer_id,
                            domain_id=domain_id,
                            detected_category=category,
                            captured_from=start,
                            captured_before=end,
                            page_size=MAX_QUERY_PAGE_SIZE,
                            continuation=continuation,
                        )
                    )
                    self._tally(page, domain_id, category, wanted_parts, tallies)
                    continuation = page.continuation
                    if continuation is None:
                        break
                if exhausted:
                    break
            if exhausted:
                break
        return _page(tallies, limit, truncated=exhausted)

    @staticmethod
    def _tally(
        page: IndexPage,
        domain_id: str,
        category: str,
        wanted_parts: frozenset[str],
        tallies: dict[tuple[str, str, str], _Tally],
    ) -> None:
        for record in page.items:
            # Defence in depth: the query is partition-scoped, but a record from another
            # partition must never be counted.
            if _text(record.domain_id) != domain_id or not _has_part(record, wanted_parts):
                continue
            subject = _subject(record)
            count = _category_count(record, category)
            if subject is None or count < 1:
                continue
            subject_id, subject_type = subject
            tally = tallies.setdefault((subject_id, domain_id, category), _Tally(subject_type))
            tally.count += count
            if len(tally.ids) < MAX_INTERACTION_IDS_PER_COUNT:
                interaction_id = _text(record.interaction_id)
                if interaction_id and interaction_id not in tally.ids:
                    tally.ids.append(interaction_id)


def _page(
    tallies: dict[tuple[str, str, str], _Tally], limit: int, *, truncated: bool
) -> FindingCountPage:
    subjects = sorted({subject_id for subject_id, _, _ in tallies})
    kept = frozenset(subjects[:limit])
    counts = tuple(
        InteractionFindingCount(
            subject_id=subject_id,
            subject_type=tally.subject_type,
            domain_id=domain_id,
            category=category,
            count=tally.count,
            interaction_ids=tuple(sorted(tally.ids)),
        )
        for (subject_id, domain_id, category), tally in sorted(tallies.items())
        if subject_id in kept
    )
    return FindingCountPage(counts=counts, truncated=truncated or len(subjects) > limit)
