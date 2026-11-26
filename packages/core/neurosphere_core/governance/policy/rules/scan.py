"""Bounded catalog reads shared by the evaluators (PRP-105 item 2).

Everything here goes through the ``CatalogRepository`` with the caller's derived scope, one
bounded page at a time, and charges the :class:`RunBudget` per document it hands out. Edges are
shown as presented lineage (``present_with_latest``): an edge a steward rejected is hidden and is
never evidence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Final

from neurosphere_contracts.policy.v1.policy_definition import PolicyAppliesTo, PolicyRule

from neurosphere_core.catalog.graph.latest import present_with_latest
from neurosphere_core.catalog.protocol import (
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    Direction,
    EdgeFilter,
    EntityFilter,
    EntityTypeName,
    PresentedEdge,
    RelationTypeName,
)
from neurosphere_core.governance.policy.rules.base import (
    MAX_FINDING_EVIDENCE,
    FindingEvidence,
    RuleContext,
    RuleFinding,
    RuleOutcome,
    strings_of,
    text_of,
)
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE

__all__ = [
    "MAX_DOMAINS_PER_FILTER",
    "MAX_EDGE_PAGES_PER_NODE",
    "AppliesTo",
    "FindingCollector",
    "entity_type_of_id",
    "iter_domain_edges",
    "iter_entities",
    "node_edges",
]

MAX_DOMAINS_PER_FILTER: Final = 100
"""``EntityFilter.domain_ids`` ceiling; more domains are read in chunks."""
MAX_EDGE_PAGES_PER_NODE: Final = 4
"""Edge pages read per node (owners, approvals); more is reported as truncated."""


def entity_type_of_id(canonical_id: str) -> str:
    """The type segment of a canonical id (``cloud:customer:source:type:id``)."""
    parts = canonical_id.split(":", 4)
    return parts[3] if len(parts) == 5 else "unknown"


class AppliesTo:
    """``PolicyAppliesTo`` as a predicate. Empty lists match everything; lists combine with AND.

    A subject with no catalog entity (a telemetry subject point) matches only when no tag or
    environment filter is set, because those values are unknown for it (null is never a match).
    """

    def __init__(self, applies_to: PolicyAppliesTo | None) -> None:
        raw = applies_to or PolicyAppliesTo()
        self.entity_types = frozenset(strings_of(raw.entity_types))
        self.tags = frozenset(strings_of(raw.tags))
        self.environments = frozenset(strings_of(raw.environments))
        self.entity_ids = frozenset(strings_of(raw.entity_ids))

    @classmethod
    def of(cls, rule: PolicyRule) -> AppliesTo:
        return cls(rule.applies_to if isinstance(rule.applies_to, PolicyAppliesTo) else None)

    def allows_type(self, entity_type: str) -> bool:
        """True when the entity-type filter is empty or names ``entity_type``."""
        return not self.entity_types or entity_type in self.entity_types

    def matches_entity(self, entity: CatalogEntity) -> bool:
        if self.entity_types and entity.entity_type not in self.entity_types:
            return False
        if self.entity_ids and entity.id not in self.entity_ids:
            return False
        if self.tags and not (self.tags & set(strings_of(getattr(entity, "tags", None)))):
            return False
        if self.environments:
            env = text_of(getattr(entity, "environment", None))
            if env is None or env not in self.environments:
                return False
        return True

    def matches_unregistered(self, subject_id: str, subject_type: str) -> bool:
        if self.entity_types and subject_type not in self.entity_types:
            return False
        if self.entity_ids and subject_id not in self.entity_ids:
            return False
        return not (self.tags or self.environments)


async def iter_entities(
    repo: CatalogRepository,
    ctx: RuleContext,
    entity_types: Sequence[EntityTypeName],
) -> AsyncIterator[CatalogEntity]:
    """Active in-scope entities of ``entity_types`` in ``ctx.domain_ids``, id order per chunk.

    Stops (with the budget marked) when the subject budget or the deadline is hit.
    """
    if not entity_types or not ctx.domain_ids:
        return
    domains = list(ctx.domain_ids)
    for start in range(0, len(domains), MAX_DOMAINS_PER_FILTER):
        flt = EntityFilter(
            entity_types=list(entity_types),
            domain_ids=domains[start : start + MAX_DOMAINS_PER_FILTER],
            lifecycle_statuses=["active"],
        )
        cursor: str | None = None
        while True:
            if ctx.budget.expired():
                return
            page = await repo.list_entities(
                ctx.scope, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            for entity in page.items:
                if not ctx.budget.take():
                    return
                yield entity
            cursor = page.next_cursor
            if cursor is None:
                break


async def _present(
    repo: CatalogRepository, ctx: RuleContext, edges: Sequence[CatalogEdge]
) -> list[PresentedEdge]:
    if not edges:
        return []
    overrides = await repo.list_overrides_for_edges(ctx.scope, [e.id for e in edges])
    shown: list[PresentedEdge] = []
    for edge in edges:
        presented = await present_with_latest(
            repo, ctx.scope, edge, overrides.get(edge.id, ()), ctx.now
        )
        if not presented.hidden:
            shown.append(presented)
    return shown


async def iter_domain_edges(
    repo: CatalogRepository, ctx: RuleContext, relation: RelationTypeName
) -> AsyncIterator[PresentedEdge]:
    """Presented (not hidden) edges of ``relation`` stored in ``ctx.domain_ids``, budgeted."""
    flt = EdgeFilter(relation_types=[relation])
    for domain_id in ctx.domain_ids:
        cursor: str | None = None
        while True:
            if ctx.budget.expired():
                return
            page = await repo.list_edges_by_domain(
                ctx.scope, domain_id, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            edges = sorted(page.items, key=lambda e: e.id)
            for presented in await _present(repo, ctx, edges):
                if not ctx.budget.take():
                    return
                yield presented
            cursor = page.next_cursor
            if cursor is None:
                break


async def node_edges(
    repo: CatalogRepository,
    ctx: RuleContext,
    node_id: str,
    direction: Direction,
    relation: RelationTypeName,
) -> list[PresentedEdge] | None:
    """Presented edges of one node; ``None`` when the page cap or the deadline cut the read."""
    flt = EdgeFilter(relation_types=[relation])
    found: list[PresentedEdge] = []
    cursor: str | None = None
    for _ in range(MAX_EDGE_PAGES_PER_NODE):
        if ctx.budget.expired():
            return None
        page = await repo.list_edges_by_node(
            ctx.scope, node_id, direction, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
        )
        found.extend(await _present(repo, ctx, sorted(page.items, key=lambda e: e.id)))
        cursor = page.next_cursor
        if cursor is None:
            return found
    ctx.budget.mark("source_truncated")
    return None


class FindingCollector:
    """Merges observations per (subject, evidence class) into one finding each.

    Evidence is de-duplicated and capped at ``MAX_FINDING_EVIDENCE``; counts add up; category
    names are unioned and sorted. Output is ordered by subject id, so runs are deterministic.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._subjects: dict[tuple[str, str], tuple[str, str | None]] = {}
        self._evidence: dict[tuple[str, str], dict[FindingEvidence, None]] = {}
        self._counts: dict[tuple[str, str], dict[str, int]] = {}
        self._categories: dict[tuple[str, str], set[str]] = {}

    def add(
        self,
        *,
        subject_id: str,
        subject_type: str,
        domain_id: str | None,
        evidence_class: str,
        evidence: Sequence[FindingEvidence],
        counts: dict[str, int] | None = None,
        categories: Sequence[str] = (),
    ) -> None:
        key = (subject_id, evidence_class)
        self._subjects.setdefault(key, (subject_type, domain_id))
        held = self._evidence.setdefault(key, {})
        for item in evidence:
            if len(held) >= MAX_FINDING_EVIDENCE:
                break
            held.setdefault(item, None)
        total = self._counts.setdefault(key, {})
        for name, value in (counts or {}).items():
            total[name] = total.get(name, 0) + value
        self._categories.setdefault(key, set()).update(categories)

    def __len__(self) -> int:
        return len(self._subjects)

    def findings(self) -> tuple[RuleFinding, ...]:
        out: list[RuleFinding] = []
        for key in sorted(self._subjects):
            subject_type, domain_id = self._subjects[key]
            out.append(
                RuleFinding(
                    subject_id=key[0],
                    subject_type=subject_type,
                    domain_id=domain_id,
                    evidence_class=key[1],
                    evidence=tuple(self._evidence[key]),
                    counts=dict(self._counts[key]),
                    categories=tuple(sorted(self._categories[key])),
                )
            )
        return tuple(out)

    def outcome(self, ctx: RuleContext) -> RuleOutcome:
        """The findings plus the budget's truncation state."""
        return RuleOutcome(
            kind=self.kind,
            findings=self.findings(),
            truncated=ctx.budget.truncated,
            reason=ctx.budget.reason,
            subjects_examined=ctx.budget.used,
        )
