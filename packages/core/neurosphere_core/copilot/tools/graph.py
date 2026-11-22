"""The ``graph_query`` copilot tool (PRP-78 item 1): bounded, structured graph questions.

Three shapes, all driven by the contract ``StructuredQuery`` (no query text of any kind):

* ``neighbors`` and ``impact_paths`` walk the catalog graph from at most ``MAX_START_IDS`` start
  nodes through ``GraphReader`` (the ``GraphQuery`` port) to at most ``MAX_GRAPH_DEPTH`` hops,
  ``MAX_GRAPH_NODES`` nodes and ``MAX_GRAPH_EDGES`` edges (server constants, below the contract
  ceiling).
* ``list`` on ``grounding_source`` together with ``access_mode`` answers "which agents read or
  write these data assets" through the PRP-73 ``AccessReader``. The shipped ``AccessQuery`` has no
  ``residency_geography`` filter, so with that filter present the tool first lists the matching
  assets itself through ``CatalogReader`` (owner decision 9, two-step), at most
  ``MAX_START_IDS`` asset ids, and then asks ``who_accesses`` about exactly those ids. An empty
  first step returns an empty result and never calls ``who_accesses`` (no ids would mean "scan
  everything").

Rules held here:

* Scope comes only from the server-derived ``IdentityScope``. Every node, edge endpoint, accessor
  and asset is checked against the ``data.read`` domains a second time; anything outside them is
  dropped, and so is everything only reachable through it (a node in a domain the caller cannot
  read never appears, not even as a path intermediate).
* A clause the tool does not implement is refused, never dropped: a dropped filter would widen
  the query the model asked for.
* Relation allowlist (``COPILOT_RELATIONS``): every contract relation except ``grants_access_to``.
  That relation carries who holds access to what, which is authorization data rather than lineage;
  the copilot answers access questions through the ``reads``/``writes`` access query instead. It
  stays refused until a later PRP gives it a dedicated, audited tool.
* Messages and logs carry fixed reasons only, never argument values.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.query.v1.structured_query import StructuredQuery
from pydantic import ValidationError

from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.catalog.graph.access import (
    MAX_ASSET_IDS,
    AccessQuery,
    AccessQueryError,
    AccessResult,
    AccessRow,
)
from neurosphere_core.catalog.protocol import (
    Direction,
    EdgeFilter,
    GraphResult,
    ImpactRequest,
    NeighborsRequest,
    PresentedEdge,
    RelationTypeName,
)
from neurosphere_core.copilot.tools.args import ToolArgs
from neurosphere_core.copilot.tools.builtin import (
    MAX_RESULT_LIMIT,
    _clamped_limit,  # pyright: ignore[reportPrivateUsage]
    _entity_domain,  # pyright: ignore[reportPrivateUsage]
    _entity_name,  # pyright: ignore[reportPrivateUsage]
    _narrow,  # pyright: ignore[reportPrivateUsage]
    _readable_domains,  # pyright: ignore[reportPrivateUsage]
    _utc_now,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.copilot.tools.errors import ToolBudgetError
from neurosphere_core.copilot.tools.models import (
    Citation,
    FreshnessPolicy,
    ToolRecord,
    ToolResult,
)
from neurosphere_core.copilot.tools.ports import AccessReader, CatalogReader, GraphReader
from neurosphere_core.copilot.tools.registry import ToolHandler, ToolSpec
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

logger = logging.getLogger("neurosphere.copilot.tools")

__all__ = [
    "COPILOT_RELATIONS",
    "MAX_GRAPH_DEPTH",
    "MAX_GRAPH_EDGES",
    "MAX_GRAPH_NODES",
    "MAX_START_IDS",
    "TOOL_NAME",
    "GraphQueryArgs",
    "graph_query_spec",
]

TOOL_NAME: Final = "graph_query"
MAX_GRAPH_DEPTH: Final = 3
MAX_GRAPH_NODES: Final = 100
MAX_GRAPH_EDGES: Final = 300
MAX_START_IDS: Final = 50
MAX_LIST_PAGES: Final = 5
"""Pages of ``grounding_source`` entities read by the geography first step."""

COPILOT_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "invokes",
        "delegates_to",
        "uses_model",
        "reads",
        "writes",
        "grounded_by",
        "owned_by",
        "depends_on",
        "supersedes",
    }
)
"""Relations the copilot may traverse: the contract enum minus ``grants_access_to``."""

_GRAPH_OPERATIONS: Final = ("neighbors", "impact_paths")
_COMMON_UNSUPPORTED: Final = (
    "fields",
    "sort",
    "group_by",
    "aggregations",
    "time_bucket",
    "time_range",
    "cursor",
)
_GRAPH_UNSUPPORTED: Final = ("filters", *_COMMON_UNSUPPORTED)
_LIST_UNSUPPORTED: Final = ("traversal", *_COMMON_UNSUPPORTED)
_DIRECTION: Final[dict[str, Direction]] = {"outgoing": "out", "incoming": "in", "both": "both"}
_LIST_FIELDS: Final = frozenset(
    {
        "domain_id",
        "sensitivity_category",
        "residency_region",
        "contains_personal_data",
        "residency_geography",
    }
)
_ACCESS_MODES: Final[dict[str, list[Literal["read", "write"]]]] = {
    "read": ["read"],
    "write": ["write"],
    "any": ["read", "write"],
}
_ACCESS_REASONS: Final = frozenset(
    {
        "unknown_region_group",
        "unknown_region",
        "max_depth_exceeded",
        "invalid_depth",
        "too_many_assets",
    }
)
_GRAPH_SOURCE: Final = "catalog_graph"
_ACCESS_SOURCE: Final = "catalog_access"

Row = tuple[str, str, str, "str | None", dict[str, Any]]


class GraphQueryArgs(ToolArgs):
    """A structured graph question. No scope field and no free text."""

    query: StructuredQuery
    access_mode: Literal["read", "write", "any"] | None = None

    def requested_budget(self) -> Budget:
        return self.query.budget


# -- shared pieces -------------------------------------------------------------------------------


def _refuse(detail: str, reason: str) -> ToolBudgetError:
    return ToolBudgetError(detail, reason=reason)


def _require_no_clauses(query: StructuredQuery, names: Sequence[str]) -> None:
    """Refuse (never drop) every clause the chosen operation does not implement."""
    if any(getattr(query, name) is not None for name in names):
        raise _refuse("query uses clauses this tool does not support", "unsupported_query")


def _rows_to_result(
    rows: Sequence[Row], clock: Callable[[], datetime], policy: FreshnessPolicy, truncated: bool
) -> ToolResult:
    """Records and citations built together from the same rows."""
    now = clock()
    records: list[ToolRecord] = []
    citations: list[Citation] = []
    for record_id, kind, source, as_of, data in rows:
        records.append(ToolRecord(record_id=record_id, kind=kind, data=data))
        citations.append(
            Citation(
                record_id=record_id,
                kind=kind,
                source=source,
                as_of=as_of,
                freshness=policy.state(as_of, now),
            )
        )
    return ToolResult(
        tool=TOOL_NAME, records=tuple(records), citations=tuple(citations), truncated=truncated
    )


# -- neighbors / impact_paths --------------------------------------------------------------------


@dataclass
class _Merged:
    nodes: dict[str, Any]
    edges: dict[str, PresentedEdge]
    paths: dict[str, tuple[list[str], list[str]]]
    truncated: bool = False


def _reachable_subgraph(
    result: GraphResult, start_id: str, readable: tuple[str, ...]
) -> tuple[dict[str, Any], dict[str, PresentedEdge], dict[str, tuple[list[str], list[str]]]]:
    """Re-filter one walk against the readable domains.

    Nodes outside them are dropped, edges touching a dropped node (or stored outside them) are
    dropped, and nodes only reachable through a dropped one are dropped with it.
    """
    allowed = set(readable)
    nodes = {n.id: n for n in result.nodes if _entity_domain(n) in allowed}
    if start_id not in nodes:
        return {}, {}, {}
    edges = {
        e.edge_id: e
        for e in result.edges
        if not e.hidden and e.domain_id in allowed and e.source_id in nodes and e.target_id in nodes
    }
    adjacency: dict[str, set[str]] = {}
    for e in edges.values():
        adjacency.setdefault(e.source_id, set()).add(e.target_id)
        adjacency.setdefault(e.target_id, set()).add(e.source_id)
    reached = {start_id}
    queue = deque([start_id])
    while queue:
        for neighbour in sorted(adjacency.get(queue.popleft(), ())):
            if neighbour not in reached:
                reached.add(neighbour)
                queue.append(neighbour)
    paths: dict[str, tuple[list[str], list[str]]] = {}
    for p in result.paths:
        if all(n in reached for n in p.node_ids) and all(e in edges for e in p.edge_ids):
            paths[p.node_ids[-1]] = (list(p.node_ids), list(p.edge_ids))
    return (
        {i: n for i, n in nodes.items() if i in reached},
        {i: e for i, e in edges.items() if e.source_id in reached and e.target_id in reached},
        paths,
    )


def _edge_row(edge: PresentedEdge) -> Row:
    data: dict[str, Any] = {
        "edge_id": edge.edge_id,
        "relation_type": edge.relation_type,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "domain_id": edge.domain_id,
        "status": edge.status,
        "confidence": edge.confidence,
        "provenance": edge.provenance.model_dump(mode="json"),
        "evidence_ids": list(edge.evidence_ids),
        "last_observed": edge.last_observed.root,
    }
    return edge.edge_id, "graph_edge", _GRAPH_SOURCE, edge.last_observed.root, data


def _node_row(node: Any, path: tuple[list[str], list[str]] | None) -> Row:
    data: dict[str, Any] = node.model_dump(mode="json")
    if path is not None:
        data["path_node_ids"], data["path_edge_ids"] = path
    return node.id, node.entity_type, _GRAPH_SOURCE, node.updated_at.root, data


def _graph_budget(query: StructuredQuery, nodes_left: int, edges_left: int) -> Budget:
    requested = query.budget
    return Budget(
        timeout_ms=requested.timeout_ms,
        limit=min(requested.limit, MAX_RESULT_LIMIT),
        max_depth=requested.max_depth,
        max_nodes=max(1, nodes_left),
        max_edges=max(1, edges_left),
    )


def _graph_request_checks(query: StructuredQuery) -> tuple[list[str], list[RelationTypeName]]:
    if query.traversal is None:
        raise _refuse("a traversal is required for this operation", "traversal_required")
    _require_no_clauses(query, _GRAPH_UNSUPPORTED)
    if not 1 <= query.budget.max_depth <= MAX_GRAPH_DEPTH:
        raise _refuse("max_depth is outside the copilot limit", "depth_denied")
    start_ids = list(dict.fromkeys(i.root for i in query.traversal.start_ids))
    if len(query.traversal.start_ids) > MAX_START_IDS:
        raise _refuse("too many start ids", "too_many_start_ids")
    relations: list[RelationTypeName] = []
    for relation in dict.fromkeys(query.traversal.relations):
        if relation not in COPILOT_RELATIONS:
            raise _refuse("relation is not allowed for the copilot", "relation_denied")
        relations.append(relation)
    if query.operation == "impact_paths" and query.traversal.direction == "both":
        raise _refuse("impact_paths needs a direction", "unsupported_query")
    return start_ids, relations


async def _walk_graph(
    graph: GraphReader, scope: IdentityScope, query: StructuredQuery, readable: tuple[str, ...]
) -> _Merged:
    start_ids, relations = _graph_request_checks(query)
    assert query.traversal is not None
    node_cap = min(query.budget.max_nodes or MAX_GRAPH_NODES, MAX_GRAPH_NODES)
    edge_cap = min(query.budget.max_edges or MAX_GRAPH_EDGES, MAX_GRAPH_EDGES)
    flt = EdgeFilter(relation_types=list(relations))
    merged = _Merged({}, {}, {})
    for start in start_ids:
        if len(merged.nodes) >= node_cap or len(merged.edges) >= edge_cap:
            merged.truncated = True
            break
        budget = _graph_budget(query, node_cap - len(merged.nodes), edge_cap - len(merged.edges))
        try:
            if query.operation == "neighbors":
                result = await graph.neighbors(
                    scope,
                    NeighborsRequest(
                        node_id=start,
                        direction=_DIRECTION[query.traversal.direction],
                        filters=flt,
                        budget=budget,
                    ),
                )
            else:
                result = await graph.impact_paths(
                    scope,
                    ImpactRequest(
                        node_id=start,
                        direction=(
                            "downstream" if query.traversal.direction == "outgoing" else "upstream"
                        ),
                        filters=flt,
                        budget=budget,
                    ),
                )
        except ForbiddenError:
            raise _refuse("graph read was denied", "graph_denied") from None
        except InvalidSchemaError:
            raise _refuse("graph query was refused", "graph_query_refused") from None
        nodes, edges, paths = _reachable_subgraph(result, start, readable)
        merged.truncated = merged.truncated or result.truncated
        merged.nodes.update(nodes)
        merged.edges.update(edges)
        merged.paths.update(paths)
    if len(merged.nodes) > node_cap:
        merged.nodes = dict(list(merged.nodes.items())[:node_cap])
        merged.truncated = True
    if len(merged.edges) > edge_cap:
        merged.edges = dict(list(merged.edges.items())[:edge_cap])
        merged.truncated = True
    # Cutting nodes can orphan edges: keep only edges whose endpoints survived.
    merged.edges = {
        i: e
        for i, e in merged.edges.items()
        if e.source_id in merged.nodes and e.target_id in merged.nodes
    }
    return merged


# -- list + access_mode --------------------------------------------------------------------------


def _list_filters(query: StructuredQuery) -> dict[str, list[Any]]:
    """Values of the supported ``eq``/``in`` filters by field. Duplicates and others are refused."""
    found: dict[str, list[Any]] = {}
    for flt in query.filters or []:
        root: Any = flt.root
        name = str(root.field.root)
        if name not in _LIST_FIELDS or name in found:
            raise _refuse("filter field is not supported by this tool", "unsupported_filter")
        if name == "contains_personal_data":
            found[name] = [root.value]
            continue
        if root.op not in ("eq", "in"):
            raise _refuse("filter operator is not supported by this tool", "unsupported_filter")
        raw = [root.value] if root.value is not None else list(root.values or [])
        if not raw:
            raise _refuse("filter value list must not be empty", "empty_filter_values")
        found[name] = [item.root for item in raw]
    return found


async def _geography_asset_ids(
    catalog: CatalogReader,
    scope: IdentityScope,
    domains: tuple[str, ...],
    filters: dict[str, list[Any]],
) -> tuple[list[str], bool]:
    """Step 1 of owner decision 9: asset ids matching the geography (and simple) filters."""
    geographies = set(filters["residency_geography"])
    categories = set(filters.get("sensitivity_category", ()))
    personal = filters.get("contains_personal_data")
    flt = EntityFilter(entity_types=["grounding_source"], domain_ids=list(domains))
    ids: list[str] = []
    cursor = None
    for _ in range(MAX_LIST_PAGES):
        page = await catalog.list_entities(
            scope, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
        )
        for item in page.items:
            if not isinstance(item, GroundingSource) or _entity_domain(item) not in domains:
                continue
            if item.residency_geography is None or item.residency_geography.root not in geographies:
                continue
            if categories:
                held = (
                    {c.root for c in item.sensitivity_categories.root}
                    if (item.sensitivity_categories is not None)
                    else set()
                )
                if not held & categories:
                    continue
            if personal is not None and item.contains_personal_data is not personal[0]:
                continue
            if len(ids) >= MAX_ASSET_IDS:
                return ids, True
            ids.append(item.id)
        cursor = page.next_cursor
        if cursor is None:
            return ids, False
    return ids, True


def _access_query(
    filters: dict[str, list[Any]],
    domains: tuple[str, ...],
    modes: list[Literal["read", "write"]],
    asset_ids: list[str],
) -> AccessQuery:
    try:
        return AccessQuery(
            asset_ids=asset_ids,
            sensitivity_categories=filters.get("sensitivity_category"),
            residency_regions=filters.get("residency_region"),
            contains_personal_data=(
                filters["contains_personal_data"][0]
                if "contains_personal_data" in filters
                else None
            ),
            domain_ids=list(domains),
            modes=modes,
        )
    except ValidationError:
        raise _refuse("filter value is not supported by this tool", "unsupported_filter") from None


def _accessor_rows(
    rows: Sequence[AccessRow], assets: dict[str, Row], readable: set[str], cap: int
) -> tuple[list[Row], bool]:
    """One record per accessor (listing each asset it touches), re-filtered by domain."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.asset_id not in assets or row.accessor_domain_id not in readable:
            continue
        entry = grouped.setdefault(
            row.accessor_id,
            {
                "accessor_id": row.accessor_id,
                "accessor_type": row.accessor_type,
                "name": row.accessor_name,
                "domain_id": row.accessor_domain_id,
                "accesses": [],
                "_as_of": row.last_observed,
            },
        )
        entry["_as_of"] = max(entry["_as_of"], row.last_observed)
        entry["accesses"].append(
            {
                "asset_id": row.asset_id,
                "mode": row.mode,
                "relation": row.relation,
                "edge_id": row.edge_id,
                "status": row.status,
                "confidence": row.confidence,
                "provenance_method": row.provenance_method,
                "provenance_source_id": row.provenance_source_id,
                "evidence_ids": list(row.evidence_ids),
                "last_observed": row.last_observed,
            }
        )
    out: list[Row] = []
    for accessor_id, entry in grouped.items():
        as_of = entry.pop("_as_of")
        out.append((accessor_id, entry["accessor_type"], _ACCESS_SOURCE, as_of, entry))
    return out[:cap], len(out) > cap


async def _access_list(
    deps: _Ports,
    scope: IdentityScope,
    args: GraphQueryArgs,
    readable: tuple[str, ...],
) -> tuple[list[Row], bool]:
    query = args.query
    assert args.access_mode is not None
    if deps.access is None:
        raise _refuse("access questions are not available", "access_unavailable")
    filters = _list_filters(query)
    domains = _narrow(readable, filters.get("domain_id"))
    limit, clamped = _clamped_limit(query.budget.limit)
    if not domains:
        return [], False
    truncated = clamped
    asset_ids: list[str] = []
    if "residency_geography" in filters:
        asset_ids, cut = await _geography_asset_ids(deps.catalog, scope, domains, filters)
        truncated = truncated or cut
        if not asset_ids:
            return [], truncated
    access_query = _access_query(filters, domains, _ACCESS_MODES[args.access_mode], asset_ids)
    try:
        result: AccessResult = await deps.access.who_accesses(scope, access_query)
    except AccessQueryError as exc:
        reason = f"access_{exc.reason}" if exc.reason in _ACCESS_REASONS else "access_query_failed"
        raise _refuse("access query was refused", reason) from None
    except (ForbiddenError, InvalidSchemaError):
        raise _refuse("access query was refused", "access_query_failed") from None
    allowed = set(readable)
    assets: dict[str, Row] = {}
    for asset in result.assets:
        if asset.domain_id in allowed:
            assets[asset.id] = (
                asset.id,
                "grounding_source",
                _ACCESS_SOURCE,
                None,
                asset.model_dump(mode="json"),
            )
    accessors, cut = _accessor_rows(result.rows, assets, allowed, limit)
    # Assets are cited only when an accessor row refers to them or no accessor was found.
    touched = {a["asset_id"] for _, _, _, _, d in accessors for a in d["accesses"]}
    asset_rows = [row for aid, row in assets.items() if aid in touched or not accessors]
    rows = [*accessors, *asset_rows][: limit * 2]
    return rows, truncated or cut or result.truncated


# -- the tool ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ports:
    graph: GraphReader
    access: AccessReader | None
    catalog: CatalogReader


def _graph_query(
    deps: _Ports, clock: Callable[[], datetime], policy: FreshnessPolicy
) -> ToolHandler:
    async def run(scope: IdentityScope, args: GraphQueryArgs) -> ToolResult:
        query = args.query
        readable = _readable_domains(scope, Permission.DATA_READ, clock())
        if query.operation in _GRAPH_OPERATIONS:
            if args.access_mode is not None:
                raise _refuse("access_mode applies to list queries only", "unsupported_query")
            merged = await _walk_graph(deps.graph, scope, query, readable)
            rows: list[Row] = [
                *(_node_row(n, merged.paths.get(i)) for i, n in merged.nodes.items()),
                *(_edge_row(e) for e in merged.edges.values()),
            ]
            return _rows_to_result(rows, clock, policy, merged.truncated)
        if query.operation != "list":
            raise _refuse("operation is not supported by this tool", "unsupported_operation")
        if _entity_name(query) != "grounding_source":
            raise _refuse("entity is not supported by this tool", "unsupported_entity")
        if args.access_mode is None:
            raise _refuse("list needs access_mode; use search_catalog", "access_mode_required")
        if query.budget.max_depth != 0:
            raise _refuse("max_depth must be 0 for list queries", "depth_denied")
        _require_no_clauses(query, _LIST_UNSUPPORTED)
        list_rows, truncated = await _access_list(deps, scope, args, readable)
        return _rows_to_result(list_rows, clock, policy, truncated)

    return run


def graph_query_spec(
    *,
    graph: GraphReader,
    access: AccessReader | None,
    catalog: CatalogReader,
    clock: Callable[[], datetime] = _utc_now,
    freshness: FreshnessPolicy = FreshnessPolicy(),  # noqa: B008 - frozen dataclass default
) -> ToolSpec:
    """The registrable ``graph_query`` spec. ``access`` is optional: without it ``list`` refuses."""
    return ToolSpec(
        TOOL_NAME,
        "Neighbours, impact paths and data-access questions over the catalog graph "
        "(bounded depth and size, readable domains only).",
        GraphQueryArgs,
        Permission.DATA_READ,
        _graph_query(_Ports(graph, access, catalog), clock, freshness),
    )
