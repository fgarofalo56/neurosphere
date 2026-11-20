"""Data access and blast-radius questions over the catalog (PRP-73 item 1).

Two bounded, structured questions; no query language is generated or executed:

* ``AccessEngine.who_accesses``: which entities have a presented ``reads`` or ``writes`` edge to
  data assets selected by id and/or application-side predicates (classification, sensitivity
  category, personal data, residency region or region group, domain).
* ``AccessEngine.dependents``: which entities depend on a failing node (``impact_paths`` with
  ``direction="upstream"``), grouped by depth with the relation path.

Rules held here (and proved in ``packages/core/tests/catalog_access``):

* Scope: assets come from ``list_entities`` / ``get_entity`` for this scope only, and every
  accessor is re-read through ``get_entity(scope, id)``; what the repository does not return is
  dropped and never counted. Hidden (rejected) edges are omitted; edges go through
  ``rules.present_edge`` like lineage does.
* Null means unassessed, never false. A predicate that cannot be decided because the asset has no
  value is "unknown"; such an asset is not scanned for accessors and, only with
  ``include_unassessed``, is reported under ``unassessed_assets`` with a count. An empty
  ``sensitivity_categories`` list is also treated as unassessed because the contract says it is
  empty both for "none declared" and "not yet assessed" (older documents load as empty).
* The sensitivity value is read through ONE function, ``effective_sensitivity``, so a later label
  layer (steward-curated value, then customer label, then inference; PRP-120) slots in there.
* Every result carries ``truncated``, ``truncated_reason`` and ``assets_scanned``. Server ceilings
  are fixed; a request budget can only lower them.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from neurosphere_contracts.catalog.v1.common import SensitivityCategory
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.query.v1.budget import Budget
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from neurosphere_core.catalog.graph.latest import present_with_latest
from neurosphere_core.catalog.graph.region_groups import (
    AccessQueryError,
    RegionGroups,
    load_region_groups,
    normalise_regions,
)
from neurosphere_core.catalog.protocol import (
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    EdgeFilter,
    EntityFilter,
    GraphQuery,
    ImpactRequest,
    PresentedEdge,
    RelationTypeName,
)
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_ACCESSORS",
    "MAX_ASSETS",
    "MAX_ASSET_IDS",
    "MAX_ASSET_PAGES",
    "MAX_DEPTH",
    "MAX_EDGE_PAGES",
    "MAX_TIMEOUT_MS",
    "AccessBudget",
    "AccessEngine",
    "AccessQuery",
    "AccessQueryError",
    "AccessResult",
    "AccessRow",
    "AssetSummary",
    "EffectiveSensitivity",
    "ScanBound",
    "TruncatedReason",
    "effective_sensitivity",
]

TruncatedReason = Literal["max_assets", "max_accessors", "max_depth", "timeout_ms"]
AccessMode = Literal["read", "write"]

MAX_ASSET_PAGES = 10
"""Pages of ``grounding_source`` entities read per question (page size ``MAX_PAGE_SIZE``)."""
MAX_ASSETS = 2000
"""Assets examined per question; more is reported as ``truncated`` (``max_assets``)."""
MAX_ACCESSORS = 1000
"""Result rows (accessors or dependents) per question; more is ``truncated`` (``max_accessors``)."""
MAX_ASSET_IDS = 50
MAX_DEPTH = 5
MAX_EDGE_PAGES = 10
"""Edge pages read per asset while collecting its accessors."""
MAX_TIMEOUT_MS = 10_000
_DEPENDENT_FAN_OUT = 500

_GRAPH_REASON: dict[str, TruncatedReason] = {"max_depth": "max_depth", "timeout_ms": "timeout_ms"}
_RELATION: dict[AccessMode, RelationTypeName] = {"read": "reads", "write": "writes"}
_MODE: dict[str, AccessMode] = {"reads": "read", "writes": "write"}


# --------------------------------------------------------------------------- models


class AccessBudget(BaseModel):
    """A request budget. It can only lower the fixed server ceilings, never raise them."""

    model_config = ConfigDict(extra="forbid")

    max_assets: Annotated[StrictInt | None, Field(ge=1)] = None
    max_accessors: Annotated[StrictInt | None, Field(ge=1)] = None
    timeout_ms: Annotated[StrictInt | None, Field(ge=1)] = None


class AccessQuery(BaseModel):
    """Which assets to look at and which accessors to list. Filters combine with AND."""

    model_config = ConfigDict(extra="forbid")

    asset_ids: list[StrictStr] = Field(default_factory=list)
    """Named assets (at most ``MAX_ASSET_IDS``; more raises ``too_many_assets``)."""
    classifications: list[StrictStr] | None = None
    sensitivity_categories: list[StrictStr] | None = None
    """Names from the contract vocabulary (``SensitivityCategory``); others fail validation."""
    contains_personal_data: StrictBool | None = None
    residency_regions: list[StrictStr] | None = None
    region_group: StrictStr | None = None
    domain_ids: list[StrictStr] | None = None
    modes: list[AccessMode] = Field(default_factory=lambda: ["read", "write"])
    include_unassessed: StrictBool = False
    budget: AccessBudget | None = None

    @field_validator("sensitivity_categories")
    @classmethod
    def _known_categories(cls, value: list[str] | None) -> list[str] | None:
        """Reject names outside the contract vocabulary (it is imported, never redefined)."""
        if value is None:
            return None
        return [SensitivityCategory.model_validate(v).root for v in value]


class AssetSummary(BaseModel):
    """An in-scope asset and the fields the question looked at (null stays null)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    display_name: str
    domain_id: str | None
    classification: str | None
    residency_region: str | None
    contains_personal_data: bool | None
    sensitivity_categories: list[str] | None


class AccessRow(BaseModel):
    """One accessor of an asset (``who_accesses``) or one dependent of a node (``dependents``).

    For ``dependents``, ``asset_id`` is the failing node, ``mode`` is ``None``, ``depth`` is the
    distance and ``relation_path`` / ``path_node_ids`` run from the dependent toward the node
    (``path_node_ids`` ends at ``asset_id``); the edge fields describe the edge next to the
    dependent. For ``who_accesses`` the path is the single edge and ``depth`` is 1.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str
    accessor_id: str
    accessor_type: str
    accessor_name: str
    accessor_domain_id: str | None
    mode: AccessMode | None
    relation: str
    edge_id: str
    status: Literal["asserted", "inferred", "curated"]
    confidence: float
    provenance_method: str
    provenance_source_id: str
    evidence_ids: list[str]
    last_observed: str
    depth: int
    relation_path: list[str]
    path_node_ids: list[str]


class ScanBound(BaseModel):
    """The effective bounds this answer ran under (ceilings after any request lowering)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_assets: int
    max_accessors: int
    timeout_ms: int
    max_depth: int | None = None


class AccessResult(BaseModel):
    """A bounded answer. ``truncated`` is True whenever a bound stopped the scan."""

    model_config = ConfigDict(extra="forbid")

    rows: list[AccessRow]
    assets: list[AssetSummary] = Field(default_factory=list)
    """Assets that matched the predicates (``who_accesses`` only)."""
    unassessed_assets: list[AssetSummary] | None = None
    """Assets whose value for a requested predicate is null; ``None`` unless asked for."""
    unassessed_count: int | None = None
    truncated: bool = False
    truncated_reason: TruncatedReason | None = None
    assets_scanned: Annotated[StrictInt, Field(ge=0)] = 0
    bound: ScanBound

    def grouped_by_depth(self) -> dict[int, list[AccessRow]]:
        """Rows grouped by depth, shallowest first (rows are already ordered by depth)."""
        groups: dict[int, list[AccessRow]] = defaultdict(list)
        for row in self.rows:
            groups[row.depth].append(row)
        return dict(sorted(groups.items()))


# --------------------------------------------------------------------------- effective values


@dataclass(frozen=True)
class EffectiveSensitivity:
    """The sensitivity of an asset as the engine reads it. ``None`` means unassessed."""

    categories: frozenset[str] | None
    contains_personal_data: bool | None


def effective_sensitivity(asset: GroundingSource) -> EffectiveSensitivity:
    """The ONE place the engine reads sensitivity (clarification 10).

    Today: the stored, declared or curated fields of the asset. A customer-label layer
    (PRP-120) changes this function only. An empty category list is unassessed, see module doc.
    """
    stored = asset.sensitivity_categories
    categories = (
        frozenset(c.root for c in stored.root) if stored is not None and stored.root else None
    )
    return EffectiveSensitivity(categories, asset.contains_personal_data)


# --------------------------------------------------------------------------- predicates

_Verdict = Literal["match", "no_match", "unknown"]


def _text(value: object) -> str | None:
    if value is None:
        return None
    root = getattr(value, "root", value)
    return None if root is None else str(root)


def _domain_of(entity: CatalogEntity) -> str | None:
    if entity.entity_type == "domain":
        return entity.id
    return _text(getattr(entity, "domain_id", None))


@dataclass(frozen=True)
class _Predicates:
    classifications: frozenset[str] | None
    categories: frozenset[str] | None
    personal_data: bool | None
    regions: frozenset[str] | None
    domains: frozenset[str] | None

    def verdict(self, asset: GroundingSource) -> _Verdict:
        """``no_match`` wins over ``unknown``; ``match`` needs every predicate decided true."""
        results: list[_Verdict] = []
        if self.domains is not None:
            results.append("match" if _domain_of(asset) in self.domains else "no_match")
        if self.classifications is not None:
            label = _text(asset.classification)
            if label is None or label == "unknown":
                results.append("unknown")
            else:
                results.append("match" if label in self.classifications else "no_match")
        if self.regions is not None:
            region = _text(asset.residency_region)
            if region is None:
                results.append("unknown")
            else:
                results.append("match" if region.lower() in self.regions else "no_match")
        effective = effective_sensitivity(asset)
        if self.categories is not None:
            if effective.categories is None:
                results.append("unknown")
            else:
                hit = bool(effective.categories & self.categories)
                results.append("match" if hit else "no_match")
        if self.personal_data is not None:
            if effective.contains_personal_data is None:
                results.append("unknown")
            else:
                results.append(
                    "match"
                    if effective.contains_personal_data is self.personal_data
                    else "no_match"
                )
        if "no_match" in results:
            return "no_match"
        return "unknown" if "unknown" in results else "match"


def _summary(asset: GroundingSource) -> AssetSummary:
    effective = effective_sensitivity(asset)
    return AssetSummary(
        id=asset.id,
        display_name=_text(asset.display_name) or asset.id,
        domain_id=_domain_of(asset),
        classification=_text(asset.classification),
        residency_region=_text(asset.residency_region),
        contains_personal_data=effective.contains_personal_data,
        sensitivity_categories=None
        if effective.categories is None
        else sorted(effective.categories),
    )


# --------------------------------------------------------------------------- engine


@dataclass
class _State:
    deadline: float
    max_assets: int
    max_accessors: int
    reason: TruncatedReason | None = None
    scanned: int = 0
    scope_cache: dict[str, CatalogEntity | None] = field(default_factory=dict)

    def truncate(self, reason: TruncatedReason) -> None:
        if self.reason is None:
            self.reason = reason


class AccessEngine:
    """Bounded access questions over a ``CatalogRepository`` and a ``GraphQuery``."""

    def __init__(
        self,
        repository: CatalogRepository,
        graph: GraphQuery,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        region_groups: RegionGroups | None = None,
    ) -> None:
        self._repo = repository
        self._graph = graph
        self._clock = clock
        self._now = now
        self._groups = region_groups

    # ------------------------------------------------------------------ who_accesses

    async def who_accesses(self, scope: IdentityScope, query: AccessQuery) -> AccessResult:
        """Accessors of the matching in-scope assets. Raises ``AccessQueryError`` on bad input."""
        if len(query.asset_ids) > MAX_ASSET_IDS:
            raise AccessQueryError("too_many_assets", f"at most {MAX_ASSET_IDS} asset ids")
        predicates = self._predicates(scope, query)
        state = self._state(query.budget)
        bound = ScanBound(
            max_assets=state.max_assets,
            max_accessors=state.max_accessors,
            timeout_ms=self._timeout_ms(query.budget),
        )

        matched: list[GroundingSource] = []
        unassessed: list[GroundingSource] = []
        async for asset in self._assets(scope, query, state):
            state.scanned += 1
            verdict = predicates.verdict(asset)
            if verdict == "match":
                matched.append(asset)
            elif verdict == "unknown":
                unassessed.append(asset)

        rows: list[AccessRow] = []
        relations: list[RelationTypeName] = [_RELATION[m] for m in dict.fromkeys(query.modes)]
        for asset in sorted(matched, key=lambda a: a.id):
            if state.reason == "timeout_ms":
                break
            if not await self._collect(scope, asset.id, relations, state, rows):
                break

        return AccessResult(
            rows=rows,
            assets=[_summary(a) for a in matched],
            unassessed_assets=[_summary(a) for a in unassessed]
            if query.include_unassessed
            else None,
            unassessed_count=len(unassessed) if query.include_unassessed else None,
            truncated=state.reason is not None,
            truncated_reason=state.reason,
            assets_scanned=state.scanned,
            bound=bound,
        )

    def _predicates(self, scope: IdentityScope, query: AccessQuery) -> _Predicates:
        regions: frozenset[str] | None = None
        if query.residency_regions is not None:
            regions = normalise_regions(query.residency_regions)
        if query.region_group is not None:
            groups = self._groups or load_region_groups()
            members = groups.regions_in(scope.cloud, query.region_group)
            regions = members if regions is None else regions | members
        return _Predicates(
            classifications=(
                None if query.classifications is None else frozenset(query.classifications)
            ),
            categories=(
                None
                if query.sensitivity_categories is None
                else frozenset(query.sensitivity_categories)
            ),
            personal_data=query.contains_personal_data,
            regions=regions,
            domains=None if query.domain_ids is None else frozenset(query.domain_ids),
        )

    def _timeout_ms(self, budget: AccessBudget | None) -> int:
        return (
            min(MAX_TIMEOUT_MS, budget.timeout_ms)
            if budget and budget.timeout_ms
            else MAX_TIMEOUT_MS
        )

    def _state(self, budget: AccessBudget | None) -> _State:
        return _State(
            deadline=self._clock() + self._timeout_ms(budget) / 1000.0,
            max_assets=min(MAX_ASSETS, budget.max_assets)
            if budget and budget.max_assets
            else MAX_ASSETS,
            max_accessors=(
                min(MAX_ACCESSORS, budget.max_accessors)
                if budget and budget.max_accessors
                else MAX_ACCESSORS
            ),
        )

    def _expired(self, state: _State) -> bool:
        if self._clock() >= state.deadline:
            state.truncate("timeout_ms")
            return True
        return False

    async def _assets(
        self, scope: IdentityScope, query: AccessQuery, state: _State
    ) -> AsyncIterator[GroundingSource]:
        """In-scope ``grounding_source`` entities, at most ``max_assets``, in id order."""
        if query.asset_ids:
            wanted = sorted(set(query.asset_ids))
            for asset_id in wanted:
                if self._expired(state):
                    return
                if state.scanned >= state.max_assets:
                    state.truncate("max_assets")
                    return
                entity = await self._repo.get_entity(scope, asset_id)
                if isinstance(entity, GroundingSource):
                    yield entity
            return
        flt = EntityFilter(entity_types=["grounding_source"], domain_ids=query.domain_ids)
        cursor: str | None = None
        for _ in range(MAX_ASSET_PAGES):
            if self._expired(state):
                return
            page = await self._repo.list_entities(
                scope, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            for entity in page.items:
                if not isinstance(entity, GroundingSource):
                    continue
                if state.scanned >= state.max_assets:
                    state.truncate("max_assets")
                    return
                yield entity
            cursor = page.next_cursor
            if cursor is None:
                return
        state.truncate("max_assets")  # pages exhausted with more entities left

    async def _collect(
        self,
        scope: IdentityScope,
        asset_id: str,
        relations: list[RelationTypeName],
        state: _State,
        rows: list[AccessRow],
    ) -> bool:
        """Append the asset's accessor rows; False when the whole question must stop."""
        flt = EdgeFilter(relation_types=relations)
        cursor: str | None = None
        for _ in range(MAX_EDGE_PAGES):
            if self._expired(state):
                return False
            page = await self._repo.list_edges_by_node(
                scope, asset_id, "in", flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            edges = sorted(page.items, key=lambda e: e.id)
            if not await self._append(scope, asset_id, edges, state, rows):
                return False
            cursor = page.next_cursor
            if cursor is None:
                return True
        state.truncate("max_accessors")  # more edges exist than the page cap reads
        return True

    async def _append(
        self,
        scope: IdentityScope,
        asset_id: str,
        edges: list[CatalogEdge],
        state: _State,
        rows: list[AccessRow],
    ) -> bool:
        sources = list(dict.fromkeys(e.source_id for e in edges))
        unseen = [s for s in sources if s not in state.scope_cache]
        if unseen:
            if self._expired(state):
                return False
            found = await asyncio.gather(*(self._repo.get_entity(scope, s) for s in unseen))
            state.scope_cache.update(zip(unseen, found, strict=True))
        visible = [e for e in edges if state.scope_cache.get(e.source_id) is not None]
        if not visible:
            return True
        if self._expired(state):
            return False
        overrides = await self._repo.list_overrides_for_edges(scope, [e.id for e in visible])
        now = self._now()
        for edge in visible:
            if self._expired(state):
                return False
            presented = await present_with_latest(
                self._repo, scope, edge, overrides.get(edge.id, ()), now
            )
            if presented.hidden:
                continue
            accessor = state.scope_cache[edge.source_id]
            assert accessor is not None  # filtered above
            if len(rows) >= state.max_accessors:
                state.truncate("max_accessors")
                return False
            rows.append(
                _row(
                    asset_id,
                    accessor,
                    presented,
                    depth=1,
                    relation_path=[presented.relation_type],
                    path_node_ids=[accessor.id, asset_id],
                    mode=_MODE.get(presented.relation_type),
                )
            )
        return True

    # ------------------------------------------------------------------ dependents

    async def dependents(
        self,
        scope: IdentityScope,
        node_id: str,
        max_depth: int,
        budget: AccessBudget | None = None,
    ) -> AccessResult:
        """Entities that depend on ``node_id``: ``impact_paths(direction="upstream")``.

        A node the scope cannot read gives an empty, untruncated result (indistinguishable from
        a node nobody depends on). Depth above ``MAX_DEPTH`` raises ``max_depth_exceeded``.
        """
        if max_depth > MAX_DEPTH:
            raise AccessQueryError("max_depth_exceeded", f"max_depth is at most {MAX_DEPTH}")
        if max_depth < 1:
            raise AccessQueryError("invalid_depth", "max_depth is at least 1")
        max_accessors = (
            min(MAX_ACCESSORS, budget.max_accessors)
            if budget and budget.max_accessors
            else MAX_ACCESSORS
        )
        timeout_ms = self._timeout_ms(budget)
        bound = ScanBound(
            max_assets=MAX_ASSETS,
            max_accessors=max_accessors,
            timeout_ms=timeout_ms,
            max_depth=max_depth,
        )
        result = await self._graph.impact_paths(
            scope,
            ImpactRequest(
                node_id=node_id,
                direction="upstream",
                budget=Budget(
                    timeout_ms=timeout_ms,
                    limit=_DEPENDENT_FAN_OUT,
                    max_depth=max_depth,
                    max_nodes=max_accessors + 1,
                ),
            ),
        )
        nodes = {n.id: n for n in result.nodes}
        edges = {e.edge_id: e for e in result.edges}
        rows: list[AccessRow] = []
        for path in result.paths:
            entity = nodes.get(path.node_ids[-1])
            if entity is None or not path.edge_ids:
                continue
            adjacent = edges.get(path.edge_ids[-1])
            if adjacent is None:
                continue
            rows.append(
                _row(
                    node_id,
                    entity,
                    adjacent,
                    depth=len(path.edge_ids),
                    relation_path=[
                        edges[e].relation_type for e in reversed(path.edge_ids) if e in edges
                    ],
                    path_node_ids=list(reversed(path.node_ids)),
                    mode=None,
                )
            )
        rows.sort(key=lambda r: (r.depth, r.accessor_id))
        reason: TruncatedReason | None = None
        if result.truncated:
            # The graph's node and edge budgets both cap how many dependents are shown.
            reason = _GRAPH_REASON.get(result.truncated_reason or "", "max_accessors")
        if len(rows) > max_accessors:
            rows = rows[:max_accessors]
            reason = reason or "max_accessors"
        return AccessResult(
            rows=rows,
            truncated=reason is not None,
            truncated_reason=reason,
            assets_scanned=result.visited_nodes,
            bound=bound,
        )


def _row(
    asset_id: str,
    accessor: CatalogEntity,
    edge: PresentedEdge,
    *,
    depth: int,
    relation_path: list[str],
    path_node_ids: list[str],
    mode: AccessMode | None,
) -> AccessRow:
    return AccessRow(
        asset_id=asset_id,
        accessor_id=accessor.id,
        accessor_type=accessor.entity_type,
        accessor_name=_text(getattr(accessor, "display_name", None)) or accessor.id,
        accessor_domain_id=_domain_of(accessor),
        mode=mode,
        relation=edge.relation_type,
        edge_id=edge.edge_id,
        status=edge.status,
        confidence=edge.confidence,
        provenance_method=edge.provenance.method,
        provenance_source_id=edge.provenance.source_id.root,
        evidence_ids=list(edge.evidence_ids),
        last_observed=edge.last_observed.root,
        depth=depth,
        relation_path=relation_path,
        path_node_ids=path_node_ids,
    )
