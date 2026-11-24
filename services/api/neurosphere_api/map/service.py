"""Viewport assembly (PRP-18 item 2): bounded, scope-filtered, clustered when over budget.

Reads, in order: the catalog repository (bounded keyset pages of the addressed domain's entities),
one bulk ``EdgesAmongQuery.edges_among`` call for edges (falling back to the bounded
``GraphQuery.neighbors`` walk, one hop per node, for a graph without it), and the hot-aggregate
status for coverage and lag. Nothing loads the whole enterprise graph:

* the entity scan is capped at :data:`SCAN_PAGE_CAP` pages and says so (``scan_limit``);
* a response carries at most the clamped node and edge budgets;
* over the node budget the top level returns one cluster node per entity kind (with
  ``member_count``) and a cluster is expanded page by page with ``cluster_id`` + ``cursor``;
* an edge is emitted only when BOTH endpoints are nodes of this response, so an edge to an
  out-of-scope or off-page node is dropped, never left dangling.

Per-node runtime metrics (PRP-49) come from the per-agent and per-model ``subject`` aggregate
series: one bounded batch read per kind for the nodes of the response, newest point of the last
two hour buckets. A node with no point, an unknown value, a person or a cluster keeps ``null`` /
``unknown`` (never 0); a failing subject read degrades to unknown metrics and ``partial``
coverage. Model nodes match by ``(provider, model_name)`` (case-insensitive), so every deployment
of one model shows the model's metrics (model-level, not deployment-level). ``context_size`` is a
catalog fact. People are pseudonymized with the PRP-06 ``PrincipalPseudonymizer``.
"""

import asyncio
import base64
import binascii
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.mcp_server import McpServer
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.catalog.v1.person import Person
from neurosphere_contracts.catalog.v1.service import Service
from neurosphere_contracts.catalog.v1.tool import Tool
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.aggregates import (
    AggregateReader,
    AggregateWindow,
    SubjectKind,
    SubjectMetricsReader,
    SubjectPoint,
    bucket_start,
    health_for_error_rate,
    subject_series_key,
)
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogEntity, CatalogRepository, EntityFilter, GraphQuery
from neurosphere_core.catalog.graph import EdgesAmongQuery
from neurosphere_core.catalog.protocol import NeighborsRequest, PresentedEdge
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError, NeuroSphereError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.map.dependencies import Clock, ViewportLimits
from neurosphere_api.map.facets import (
    DERIVED_RELATIONS,
    DERIVED_SUBJECT_TYPES,
    cluster_facets,
    derive_health,
    facets_of,
)
from neurosphere_api.map.models import (
    Coverage,
    Health,
    NodeKind,
    NodeMetrics,
    Provenance,
    TruncationReason,
    ViewportEdge,
    ViewportNode,
    ViewportResponse,
)
from neurosphere_api.map.settings import MapSettings

__all__ = [
    "SCAN_PAGE_CAP",
    "VIEWPORT_ENTITY_TYPES",
    "build_viewport",
    "model_deployment_ids",
    "provenance_of",
]

SCAN_PAGE_CAP: Final = 20
"""At most 20 x 500 entities are scanned for the cluster counts of one request."""
_PAGE: Final = 500
_EDGE_CHUNK: Final = 16
_NEIGHBOR_TIMEOUT_MS: Final = 5000
_BULK_TIMEOUT_MS: Final = 10_000
_BULK_MAX_NODES: Final = 5000  # Budget contract ceiling
_BULK_MAX_EDGES: Final = 20_000  # Budget contract ceiling
_CLUSTER_PREFIX: Final = "kind:"
_SUBJECT_TIMEOUT_S: Final = 5.0

logger = logging.getLogger(__name__)

VIEWPORT_ENTITY_TYPES: Final = (
    "agent",
    "grounding_source",
    "model_deployment",
    "person",
    "service",
    "tool",
    "mcp_server",
)
_KIND: Final[dict[str, NodeKind]] = {
    "person": "person",
    "agent": "agent",
    "model_deployment": "model",
    "grounding_source": "source",
    "service": "service",
    "tool": "tool",
    "mcp_server": "mcp_server",
}
_CLUSTER_LABEL: Final[dict[str, str]] = {
    "person": "People",
    "agent": "Agents",
    "model_deployment": "Models",
    "grounding_source": "Sources",
    "service": "Services",
    "tool": "Tools",
    "mcp_server": "MCP servers",
}
_LIVE: Final = ("draft", "active", "deprecated")


def provenance_of(edge: PresentedEdge) -> Provenance:
    """``inferred`` stays inferred; otherwise evidence-backed edges are ``observed`` and an edge
    with no evidence is ``declared``."""
    if edge.status == "inferred":
        return "inferred"
    return "observed" if edge.evidence_ids else "declared"


def _raw(value: Any) -> Any:
    return getattr(value, "root", value)


def model_deployment_ids(
    entities: Sequence[CatalogEntity], provider: str, model_name: str
) -> list[str]:
    """Ids of every model deployment of ``(provider, model_name)`` (case-insensitive) among
    ``entities``: maps a ``model:<provider>/<model>`` delta id to the viewport's model node ids."""
    want = (provider.strip().lower(), model_name.strip().lower())
    return sorted(
        e.id
        for e in entities
        if isinstance(e, ModelDeployment)
        and (str(_raw(e.provider)).strip().lower(), e.model_name.strip().lower()) == want
    )


def _encode_cursor(entity_type: str, repo_cursor: str) -> str:
    raw = f"{entity_type}|{repo_cursor}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str, entity_type: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor") from exc
    kind, sep, inner = raw.partition("|")
    if not sep or kind != entity_type or not inner:
        raise InvalidSchemaError("cursor does not belong to this cluster", reason="invalid_cursor")
    return inner


def _cluster_type(cluster_id: str) -> str:
    entity_type = cluster_id.removeprefix(_CLUSTER_PREFIX)
    if not cluster_id.startswith(_CLUSTER_PREFIX) or entity_type not in VIEWPORT_ENTITY_TYPES:
        raise InvalidSchemaError("unknown cluster_id", reason="invalid_cluster")
    return entity_type


@dataclass
class _Edges:
    items: dict[str, PresentedEdge] = field(default_factory=dict)
    reason: TruncationReason | None = None
    incomplete: bool = False


@dataclass(frozen=True)
class _Walk:
    edges: list[PresentedEdge]
    truncated: bool
    truncated_reason: str | None


class _Builder:
    def __init__(
        self,
        scope: IdentityScope,
        domain_id: str,
        repository: CatalogRepository,
        graph: GraphQuery,
        reader: AggregateReader,
        pseudonymizer: PrincipalPseudonymizer,
        clock: Clock,
        limits: ViewportLimits,
        settings: MapSettings | None = None,
    ) -> None:
        self.settings = settings or MapSettings()
        self.scope = scope
        self.domain_id = domain_id
        self.repository = repository
        self.graph = graph
        self.reader = reader
        self.pseudonymizer = pseudonymizer
        self.clock = clock
        self.limits = limits
        self.subjects: dict[str, SubjectPoint] = {}  # entity id -> newest subject point
        self.subjects_failed = False

    def _filter(self, entity_types: list[str]) -> EntityFilter:
        return EntityFilter.model_validate(
            {
                "entity_types": entity_types,
                "domain_ids": [self.domain_id],
                "lifecycle_statuses": list(_LIVE),
            }
        )

    async def scan(self) -> tuple[list[CatalogEntity], bool]:
        """Entities of the domain, at most ``SCAN_PAGE_CAP`` pages; flag when more remain."""
        found: list[CatalogEntity] = []
        cursor: str | None = None
        for _ in range(SCAN_PAGE_CAP):
            page = await self.repository.list_entities(
                self.scope,
                self._filter(list(VIEWPORT_ENTITY_TYPES)),
                PageRequest(page_size=_PAGE, cursor=cursor),
            )
            found.extend(self._in_domain(page.items))
            cursor = page.next_cursor
            if cursor is None:
                return found, False
        return found, True

    async def page_of_kind(
        self, entity_type: str, cursor: str | None, want: int
    ) -> tuple[list[CatalogEntity], str | None]:
        """Up to ``want`` entities of one kind plus the repository cursor of what follows."""
        out: list[CatalogEntity] = []
        repo_cursor = None if cursor is None else _decode_cursor(cursor, entity_type)
        while True:
            page = await self.repository.list_entities(
                self.scope,
                self._filter([entity_type]),
                PageRequest(page_size=min(_PAGE, want - len(out)), cursor=repo_cursor),
            )
            out.extend(self._in_domain(page.items))
            repo_cursor = page.next_cursor
            if repo_cursor is None:
                return out, None
            if len(out) >= want:
                return out, _encode_cursor(entity_type, repo_cursor)

    def _in_domain(self, items: tuple[CatalogEntity, ...]) -> list[CatalogEntity]:
        # The repository filters by scope and by the requested domain; this re-checks both so
        # a misbehaving store cannot leak a node from another domain into the response.
        allowed = set(self.scope.allowed_domains)
        return [
            e
            for e in items
            if getattr(getattr(e, "domain_id", None), "root", None) == self.domain_id
            and self.domain_id in allowed
            and e.customer_id.root == self.scope.customer_id
        ]

    # ------------------------------------------------------------------ nodes

    @staticmethod
    def subject_key_of(entity: CatalogEntity) -> str | None:
        """Series key of an agent, model deployment, tool or service; ``None`` for everything
        else. An MCP server never has a subject key (telemetry carries no MCP-server id)."""
        if isinstance(entity, Agent):
            return subject_series_key("agent", entity.id)
        if isinstance(entity, Tool):
            return subject_series_key("tool", entity.id)
        if isinstance(entity, Service):
            return subject_series_key("service", entity.id)
        if isinstance(entity, ModelDeployment):
            provider = str(getattr(entity.provider, "root", entity.provider))
            return subject_series_key("model", provider, entity.model_name)
        return None

    async def load_subjects(self, entities: list[CatalogEntity]) -> None:
        """Newest subject point per agent and model of the response (bounded batch reads).

        Only runs when the reader implements ``SubjectMetricsReader``. Any failure leaves the
        metrics unknown and flags the response ``partial``; it never fails the viewport.
        """
        reader = self.reader
        if not isinstance(reader, SubjectMetricsReader):
            return
        kinds: tuple[SubjectKind, ...] = ("agent", "model", "tool", "service")
        keys: dict[SubjectKind, list[str]] = {k: [] for k in kinds}
        owners: dict[str, list[str]] = {}
        for entity in entities:
            key = self.subject_key_of(entity)
            if key is None:
                continue
            keys[_kind_of_key(key)].append(key)
            owners.setdefault(key, []).append(entity.id)
        if not owners:
            return
        end = bucket_start(self.clock(), "hour") + timedelta(hours=1)
        window = AggregateWindow(start=end - timedelta(hours=2), end=end)
        try:
            for kind in kinds:
                if not keys[kind]:
                    continue
                found = await asyncio.wait_for(
                    reader.latest_subject_points(
                        self.scope.customer_id,
                        self.domain_id,
                        kind,
                        sorted(set(keys[kind])),
                        window,
                    ),
                    _SUBJECT_TIMEOUT_S,
                )
                self.subjects_failed = self.subjects_failed or found.truncated
                for key, point in found.points.items():
                    for entity_id in owners.get(key, []):
                        self.subjects[entity_id] = point
        except Exception:
            logger.warning("subject metrics read failed; node metrics are unknown")
            self.subjects.clear()
            self.subjects_failed = True

    def _metrics_of(self, entity_id: str, derived: Health | None = None) -> NodeMetrics:
        point = self.subjects.get(entity_id)
        if point is None:
            return NodeMetrics() if derived is None else NodeMetrics(health=derived)
        tokens = [t for t in (point.input_tokens, point.output_tokens) if t is not None]
        return NodeMetrics(
            frequency=float(point.event_count),
            latency_p95_ms=None if point.p95_ms is None else float(point.p95_ms),
            tokens=float(sum(tokens)) if tokens else None,
            health=health_for_error_rate(point.error_rate),
        )

    def derived_health_for(
        self, entities: Sequence[CatalogEntity], edges: Sequence[PresentedEdge]
    ) -> dict[str, Health]:
        """Fallback health of each service, tool or MCP server WITHOUT a subject point, from the
        measured health of its direct dependents in this response (clarification 5).

        Only non-``unknown`` results are returned; a node with a point is never in the result.
        """
        dependents: dict[str, list[str]] = {}
        for edge in edges:
            if edge.relation_type in DERIVED_RELATIONS:
                dependents.setdefault(edge.target_id, []).append(edge.source_id)
        out: dict[str, Health] = {}
        for entity in entities:
            if entity.entity_type not in DERIVED_SUBJECT_TYPES or entity.id in self.subjects:
                continue
            sources = sorted(set(dependents.get(entity.id, [])))
            health = derive_health(
                [self._measured_health(s) for s in sources],
                failing_ratio=self.settings.derived_failing_ratio,
                degraded_ratio=self.settings.derived_degraded_ratio,
            )
            if health != "unknown":
                out[entity.id] = health
        return out

    def _measured_health(self, entity_id: str) -> Health:
        point = self.subjects.get(entity_id)
        return "unknown" if point is None else health_for_error_rate(point.error_rate)

    def node_for(
        self,
        entity: CatalogEntity,
        cluster_id: str | None,
        derived: Health | None = None,
    ) -> ViewportNode:
        kind = _KIND[entity.entity_type]
        point = self.subjects.get(entity.id)
        inferred = point is None and derived is not None
        metrics = self._metrics_of(entity.id, derived)
        facets = facets_of(entity, point, derived_health=derived)
        if isinstance(entity, Person):
            label = self.pseudonymizer.pseudonym(self.scope.customer_id, entity.id)
            return ViewportNode(
                id=label,
                kind=kind,
                label=label,
                cluster_id=cluster_id,
                metrics=metrics,
                facets=facets,
            )
        if isinstance(entity, ModelDeployment):
            window = entity.context_window_tokens
            metrics = metrics.model_copy(
                update={"context_size": None if window is None else window.root}
            )
            label = entity.deployment_name
        elif isinstance(entity, Agent | GroundingSource | Service | Tool | McpServer):
            label = entity.display_name.root
        else:  # pragma: no cover - only VIEWPORT_ENTITY_TYPES are ever listed
            label = entity.id
        return ViewportNode(
            id=entity.id,
            kind=kind,
            label=label,
            cluster_id=cluster_id,
            metrics=metrics,
            facets=facets,
            health_inferred=inferred,
        )

    def public_id(self, entity: CatalogEntity) -> str:
        if entity.entity_type == "person":
            return self.pseudonymizer.pseudonym(self.scope.customer_id, entity.id)
        return entity.id

    # ------------------------------------------------------------------ edges

    async def edges_among(self, ids: set[str], edge_budget: int) -> _Edges:
        """One bulk call when the graph supports it, else the per-node walk."""
        graph = self.graph
        if isinstance(graph, EdgesAmongQuery):
            return await self._bulk_edges(graph, ids, edge_budget)
        return await self._walked_edges(ids, edge_budget)

    async def _bulk_edges(self, graph: EdgesAmongQuery, ids: set[str], edge_budget: int) -> _Edges:
        budget = Budget(
            timeout_ms=_BULK_TIMEOUT_MS,
            limit=500,
            max_depth=1,
            max_nodes=max(1, min(len(ids), _BULK_MAX_NODES)),
            max_edges=min(edge_budget + 1, _BULK_MAX_EDGES),
        )
        found = await graph.edges_among(self.scope, ids, budget)
        result = _Edges()
        for edge in found.edges:
            if edge.source_id in ids and edge.target_id in ids:
                result.items[edge.edge_id] = edge
        if len(result.items) > edge_budget:
            keep = sorted(result.items)[:edge_budget]
            result.items = {k: result.items[k] for k in keep}
            result.reason = "edge_budget"
        elif found.truncated:
            result.incomplete = True
        return result

    async def _walked_edges(self, ids: set[str], edge_budget: int) -> _Edges:
        result = _Edges()
        ordered = sorted(ids)
        for start in range(0, len(ordered), _EDGE_CHUNK):
            chunk = ordered[start : start + _EDGE_CHUNK]
            walks = await asyncio.gather(*(self._neighbors(node_id) for node_id in chunk))
            for walk in walks:
                if walk.truncated and walk.truncated_reason in {
                    "max_nodes",
                    "max_edges",
                    "timeout_ms",
                }:
                    result.incomplete = True
                for edge in walk.edges:
                    if edge.source_id in ids and edge.target_id in ids:
                        result.items.setdefault(edge.edge_id, edge)
            if len(result.items) > edge_budget:
                keep = sorted(result.items)[:edge_budget]
                result.items = {k: result.items[k] for k in keep}
                result.reason = "edge_budget"
                return result
        return result

    async def _neighbors(self, node_id: str) -> _Walk:
        budget = Budget(
            timeout_ms=_NEIGHBOR_TIMEOUT_MS,
            limit=500,
            max_depth=1,
            max_nodes=5000,
            max_edges=20000,
        )
        request = NeighborsRequest(node_id=node_id, direction="out", budget=budget)
        found = await self.graph.neighbors(self.scope, request)
        return _Walk(
            edges=found.edges, truncated=found.truncated, truncated_reason=found.truncated_reason
        )

    # ------------------------------------------------------------------ coverage

    async def coverage(self, *, incomplete: bool) -> Coverage:
        try:
            status = await self.reader.status(self.scope.customer_id)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "aggregates are unavailable", reason="aggregates_unavailable"
            ) from exc
        lag = status.lag_seconds(self.clock()) if status is not None else None
        as_of = status.watermark if status is not None else None
        if lag is None:
            return Coverage(state="unknown", lag_seconds=None, as_of=as_of)
        if lag > self.limits.delayed_after_seconds:
            return Coverage(state="delayed", lag_seconds=lag, as_of=as_of)
        state = "partial" if incomplete else "complete"
        return Coverage(state=state, lag_seconds=lag, as_of=as_of)


def _edge_out(edge: PresentedEdge, ids: dict[str, str]) -> ViewportEdge:
    return ViewportEdge(
        id=edge.edge_id,
        source=ids[edge.source_id],
        target=ids[edge.target_id],
        provenance=provenance_of(edge),
        last_observed_at=edge.last_observed.root,
    )


def _clamp(requested: int, ceiling: int) -> int:
    return max(1, min(requested, ceiling))


async def build_viewport(
    *,
    scope: IdentityScope,
    domain_id: str,
    cluster_id: str | None,
    cursor: str | None,
    node_budget: int,
    edge_budget: int,
    repository: CatalogRepository,
    graph: GraphQuery,
    reader: AggregateReader,
    pseudonymizer: PrincipalPseudonymizer,
    clock: Clock,
    limits: ViewportLimits,
    settings: MapSettings | None = None,
) -> ViewportResponse:
    nodes_cap = _clamp(node_budget, limits.max_nodes)
    edges_cap = _clamp(edge_budget, limits.max_edges)
    b = _Builder(
        scope, domain_id, repository, graph, reader, pseudonymizer, clock, limits, settings
    )
    reason: TruncationReason | None = None
    next_cursor: str | None = None
    entities: list[CatalogEntity]
    clusters: list[ViewportNode] = []
    scan_capped = False
    member_cluster: str | None = None

    if cluster_id is None:
        if cursor is not None:
            raise InvalidSchemaError("cursor requires cluster_id", reason="invalid_cursor")
        scanned, scan_capped = await b.scan()
        if len(scanned) <= nodes_cap:
            entities = scanned
        else:
            entities = []
            counts = Counter(e.entity_type for e in scanned)
            for entity_type in VIEWPORT_ENTITY_TYPES:
                if counts[entity_type]:
                    cid = f"{_CLUSTER_PREFIX}{entity_type}"
                    clusters.append(
                        ViewportNode(
                            id=cid,
                            kind="cluster",
                            label=_CLUSTER_LABEL[entity_type],
                            cluster_id=cid,
                            member_count=counts[entity_type],
                            facets=cluster_facets(),
                        )
                    )
            reason = "node_budget"
    else:
        entity_type = _cluster_type(cluster_id)
        member_cluster = cluster_id
        entities, next_cursor = await b.page_of_kind(entity_type, cursor, nodes_cap)
        if next_cursor is not None:
            reason = "node_budget"

    if reason is None and scan_capped:
        reason = "scan_limit"

    public = {e.id: b.public_id(e) for e in entities}
    edges_state = _Edges()
    if entities:
        edges_state = await b.edges_among(set(public), edges_cap)
        if edges_state.reason is not None and reason is None:
            reason = edges_state.reason
    if edges_state.incomplete and reason is None:
        reason = "traversal_incomplete"

    await b.load_subjects(entities)
    derived = b.derived_health_for(entities, list(edges_state.items.values()))
    nodes = [b.node_for(e, member_cluster, derived.get(e.id)) for e in entities]
    nodes = _sub_agents(nodes, edges_state, public)
    nodes.extend(clusters)
    nodes = nodes[: limits.max_nodes]  # belt and braces: never above the hard ceiling
    edges = [_edge_out(e, public) for e in sorted(edges_state.items.values(), key=_edge_key)]
    coverage = await b.coverage(
        incomplete=edges_state.incomplete or scan_capped or b.subjects_failed
    )
    return ViewportResponse(
        domain_id=domain_id,
        nodes=nodes,
        edges=edges,
        truncated=reason is not None,
        truncation_reason=reason,
        next_cursor=next_cursor,
        coverage=coverage,
    )


def _kind_of_key(key: str) -> SubjectKind:
    prefix = key.partition(":")[0]
    if prefix == "agent":
        return "agent"
    if prefix == "tool":
        return "tool"
    if prefix == "service":
        return "service"
    return "model"


def _edge_key(edge: PresentedEdge) -> str:
    return edge.edge_id


def _sub_agents(
    nodes: list[ViewportNode],
    edges: _Edges,
    public: dict[str, str],
) -> list[ViewportNode]:
    """An agent that is the target of a ``delegates_to`` edge is shown as ``sub_agent``."""
    delegated = {
        public[e.target_id]
        for e in edges.items.values()
        if e.relation_type == "delegates_to" and e.target_id in public
    }
    if not delegated:
        return nodes
    return [
        n.model_copy(update={"kind": "sub_agent"}) if n.kind == "agent" and n.id in delegated else n
        for n in nodes
    ]
