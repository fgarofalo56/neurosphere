"""The ``CatalogRepository`` and ``GraphQuery`` protocols (PRP-10, ADR-0005).

These are the stable interfaces items 1-5 code against. Cosmos NoSQL adjacency (and an
in-memory fixture) implement ``CatalogRepository`` under ``catalog/repo``; ``GraphQuery`` is
built on the repository under ``catalog/graph``.

Rules common to every method:

* The FIRST parameter is the server-derived ``IdentityScope``. There is no default and no
  overload without it, so a call without a scope is a type error (pyright) and a
  ``TypeError`` at runtime. ``domain_id``/``customer_id`` values inside caller-supplied
  documents or filters are never trusted for authorization: implementations check them
  against the scope.
* Out-of-scope documents are indistinguishable from missing ones on reads (``None`` or
  absent from results); writes into a domain outside the scope raise ``ForbiddenError``.
* Optimistic concurrency uses the document ``etag``; a mismatch raises ``StaleVersionError``
  (``stale_version``). A caller that omits the ETag cannot express an update here: the type
  requires it, and the API layer maps a missing ETag to ``invalid_schema`` (item 5).
* Filters are structured and allowlisted. No query text from callers or models is ever
  passed to a store.
* Every list is bounded by ``PageRequest`` (max 500) or a ``Budget``; nothing is unlimited.
* Raw telemetry never lives here. Edges hold evidence IDs that point at ledger or archive
  records.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Protocol, runtime_checkable

from neurosphere_contracts.catalog.v1 import common
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.agent_version import AgentVersion
from neurosphere_contracts.catalog.v1.alias import Alias
from neurosphere_contracts.catalog.v1.delegates_to import DelegatesToRelation
from neurosphere_contracts.catalog.v1.depends_on import DependsOnRelation
from neurosphere_contracts.catalog.v1.domain import Domain
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.grant import Grant
from neurosphere_contracts.catalog.v1.grants_access_to import GrantsAccessToRelation
from neurosphere_contracts.catalog.v1.grounded_by import GroundedByRelation
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_contracts.catalog.v1.mcp_server import McpServer
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment
from neurosphere_contracts.catalog.v1.owned_by import OwnedByRelation
from neurosphere_contracts.catalog.v1.owner import Owner
from neurosphere_contracts.catalog.v1.person import Person
from neurosphere_contracts.catalog.v1.policy import Policy
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.catalog.v1.recommendation_reference import RecommendationReference
from neurosphere_contracts.catalog.v1.run_reference import RunReference
from neurosphere_contracts.catalog.v1.service import Service
from neurosphere_contracts.catalog.v1.supersedes import SupersedesRelation
from neurosphere_contracts.catalog.v1.tool import Tool
from neurosphere_contracts.catalog.v1.uses_model import UsesModelRelation
from neurosphere_contracts.catalog.v1.writes import WritesRelation
from neurosphere_contracts.query.v1.budget import Budget
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

CANONICAL_ID_PATTERN = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
CanonicalIdStr = Annotated[StrictStr, Field(max_length=512, pattern=CANONICAL_ID_PATTERN)]
EtagStr = Annotated[StrictStr, Field(min_length=1, max_length=256)]
EvidenceIdStr = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$")]

EntityTypeName = Literal[
    "person",
    "agent",
    "agent_version",
    "model_deployment",
    "grounding_source",
    "tool",
    "service",
    "domain",
    "owner",
    "policy",
    "recommendation",
    "run_reference",
    "grant",
    "mcp_server",
]
RelationTypeName = Literal[
    "invokes",
    "delegates_to",
    "uses_model",
    "reads",
    "writes",
    "grounded_by",
    "owned_by",
    "depends_on",
    "supersedes",
    "grants_access_to",
]
LifecycleName = Literal["draft", "active", "deprecated", "retired"]
Direction = Literal["out", "in", "both"]

CatalogEntity = (
    Person
    | Agent
    | AgentVersion
    | ModelDeployment
    | GroundingSource
    | Tool
    | Service
    | Domain
    | Owner
    | Policy
    | RecommendationReference
    | RunReference
    | Grant
    | McpServer
)
"""Any of the 14 versioned entity documents (generated contract models)."""

CatalogEdge = (
    InvokesRelation
    | DelegatesToRelation
    | UsesModelRelation
    | ReadsRelation
    | WritesRelation
    | GroundedByRelation
    | OwnedByRelation
    | DependsOnRelation
    | SupersedesRelation
    | GrantsAccessToRelation
)
"""Any of the 10 relation edge documents (generated contract models)."""

MAX_OVERRIDES_PER_EDGE = 200
MAX_EDGES_PER_OVERRIDE_BATCH = 500


# --------------------------------------------------------------------------- filters


class EntityFilter(BaseModel):
    """Allowlisted entity filters, combined with AND. They can only narrow the scope."""

    model_config = ConfigDict(extra="forbid")

    entity_types: Annotated[list[EntityTypeName] | None, Field(max_length=14)] = None
    domain_ids: Annotated[list[CanonicalIdStr] | None, Field(max_length=100)] = None
    lifecycle_statuses: Annotated[list[LifecycleName] | None, Field(max_length=4)] = None


class EdgeFilter(BaseModel):
    """Allowlisted edge filters, combined with AND."""

    model_config = ConfigDict(extra="forbid")

    relation_types: Annotated[list[RelationTypeName] | None, Field(max_length=10)] = None
    statuses: Annotated[
        list[Literal["asserted", "inferred", "curated"]] | None, Field(max_length=3)
    ] = None


class AliasKey(BaseModel):
    """Lookup key of an alias (one active alias per key, per the Alias contract)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias_source_id: Annotated[StrictStr, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    alias_kind: Literal["external_id", "display_name", "previous_canonical_id", "source_native_id"]
    alias_value: Annotated[StrictStr, Field(min_length=1, max_length=512)]


class EdgeObservation(BaseModel):
    """One raw observation of an edge, stored apart from the (curated) edge document.

    ``id`` is deterministic for the same input so replays are idempotent. Observations are
    queryable by Auditor scope only; the presented lineage never depends on them directly.
    """

    model_config = ConfigDict(extra="forbid")

    id: EvidenceIdStr
    edge_id: CanonicalIdStr
    relation_type: RelationTypeName
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[StrictStr, Field(pattern=r"^[a-z0-9._-]{1,128}$")]
    domain_id: CanonicalIdStr
    observed_at: common.Timestamp
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    validity: common.Validity
    provenance: common.Provenance
    evidence_ids: Annotated[list[EvidenceIdStr], Field(max_length=1000)]
    security_evidence_ids: Annotated[list[EvidenceIdStr], Field(max_length=1000)]


# --------------------------------------------------------------------------- repository


@runtime_checkable
class CatalogRepository(Protocol):
    """Versioned, scope-filtered storage of catalog entities, edges, aliases and overrides."""

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        """The entity, or None if missing OR outside ``scope`` (indistinguishable)."""
        ...

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        """Insert a new entity at version 1 and return it with its assigned ``etag``.

        Raises ``ForbiddenError`` if the entity's cloud, customer or domain is outside the
        scope, and ``InvalidSchemaError`` if the ID is malformed or already exists.
        """
        ...

    async def update_entity(
        self, scope: IdentityScope, entity: CatalogEntity, expected_etag: str
    ) -> CatalogEntity:
        """Replace the entity if its stored ``etag`` equals ``expected_etag``.

        Returns the new version (``version`` + 1, new ``etag``). Raises ``StaleVersionError``
        on mismatch (two concurrent edits with the same ETag: the second fails),
        ``ForbiddenError`` out of scope, ``InvalidSchemaError`` if the entity does not exist.
        """
        ...

    async def deprecate_entity(
        self, scope: IdentityScope, entity_id: str, expected_etag: str
    ) -> CatalogEntity:
        """Set ``lifecycle_status`` to ``deprecated`` under the same ETag rules as update.

        Deprecation is a lifecycle state, not deletion: the document and its edges remain.
        """
        ...

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        """Entities in scope matching ``flt``, ordered by ID, one bounded page.

        Domains in ``flt.domain_ids`` outside the scope are silently dropped (the filter can
        narrow the scope, never widen it).
        """
        ...

    async def put_alias(self, scope: IdentityScope, alias: Alias) -> Alias:
        """Register an alias. Raises ``InvalidSchemaError`` if an ACTIVE alias with the same
        ``AliasKey`` already maps to a different canonical ID (an alias resolves to exactly
        one canonical ID) and ``ForbiddenError`` when out of scope. Idempotent for the same
        mapping.
        """
        ...

    async def resolve_alias(self, scope: IdentityScope, key: AliasKey) -> str | None:
        """The one canonical ID the active alias maps to, or None (missing or out of scope)."""
        ...

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        """The stored (observed) edge, or None if missing or outside ``scope``.

        This is the observed document. Presented lineage is computed with
        ``rules.present_edge`` over the edge plus its overrides.
        """
        ...

    async def put_edge(
        self, scope: IdentityScope, edge: CatalogEdge, expected_etag: str | None
    ) -> CatalogEdge:
        """Create (``expected_etag=None``) or replace an edge under ETag concurrency.

        Raises ``StaleVersionError`` on mismatch or when creating an existing ID,
        ``ForbiddenError`` out of scope, ``InvalidSchemaError`` for an inferred edge without
        provenance or evidence IDs, or a new version that drops prior evidence or security
        evidence (evidence is append-only).
        """
        ...

    async def list_edges_by_node(
        self,
        scope: IdentityScope,
        node_id: str,
        direction: Direction,
        flt: EdgeFilter,
        page: PageRequest,
    ) -> Page[CatalogEdge]:
        """Stored edges touching ``node_id`` whose own ``domain_id`` is in ``scope``.

        An empty page is returned when ``node_id`` itself is out of scope. Whether the OTHER
        endpoint is in scope is a graph-level decision (``GraphQuery`` excludes such nodes,
        including as path intermediates); this call filters on the edge document only.
        """
        ...

    async def record_observation(self, scope: IdentityScope, observation: EdgeObservation) -> bool:
        """Store a raw observation; return False when ``observation.id`` already exists.

        Always succeeds regardless of locks: locks affect presented lineage, never
        observations.
        """
        ...

    async def list_observations(
        self, scope: IdentityScope, edge_id: str, page: PageRequest
    ) -> Page[EdgeObservation]:
        """Raw observations, newest first. Auditor scope only.

        Raises ``ForbiddenError`` unless the scope holds a ``security_auditor`` role for the
        edge's domain.
        """
        ...

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        """Store an immutable steward decision.

        Raises ``StaleVersionError`` when ``expected_edge_etag`` no longer equals the edge's
        current ETag, ``ForbiddenError`` when the actor's scope does not cover the edge's
        domain, ``InvalidSchemaError`` if the edge does not exist. Idempotent on the same
        override ``id`` and content. Overrides never modify evidence on the edge.
        """
        ...

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        """Overrides of one edge in decision order (``decided_at``, then ``id``), bounded by
        ``MAX_OVERRIDES_PER_EDGE``. Empty when the edge is out of scope.
        """
        ...

    async def list_overrides_for_edges(
        self, scope: IdentityScope, edge_ids: Sequence[str]
    ) -> dict[str, tuple[EdgeOverride, ...]]:
        """Batch form of ``list_overrides`` for graph traversals (at most
        ``MAX_EDGES_PER_OVERRIDE_BATCH`` IDs; more raises ``InvalidSchemaError``).
        Out-of-scope edges are omitted from the result.
        """
        ...


# --------------------------------------------------------------------------- graph


class PresentedEdge(BaseModel):
    """An edge as shown to users: observed facts after curation (locks, overrides, rejects).

    Evidence and security evidence are always the full union (observed plus anything a
    steward added); they are never reduced by a decision. ``hidden`` is True when a curated
    reject hides the edge from presented lineage (Auditors can still see it).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: CanonicalIdStr
    relation_type: RelationTypeName
    source_id: CanonicalIdStr
    target_id: CanonicalIdStr
    domain_id: CanonicalIdStr
    hidden: bool
    status: Literal["asserted", "inferred", "curated"]
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    validity: common.Validity
    lock: common.Lock
    """The ACTIVE lock (``locked=False`` when none applies or the lock expired)."""
    curation: common.Curation | None
    evidence_ids: list[EvidenceIdStr]
    security_evidence_ids: list[EvidenceIdStr]
    first_observed: common.Timestamp
    last_observed: common.Timestamp
    pinned: bool
    """True when an active lock pins confidence, validity and status."""
    override_ids: list[str]
    """IDs of the steward decisions that shaped this presentation, in order."""


class GraphPath(BaseModel):
    """One impact path: alternating node and edge IDs (``len(node_ids) == len(edge_ids)+1``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_ids: Annotated[list[CanonicalIdStr], Field(min_length=1, max_length=6)]
    edge_ids: Annotated[list[CanonicalIdStr], Field(max_length=5)]


class GraphResult(BaseModel):
    """A bounded, scope-filtered subgraph.

    ``truncated`` is True when a budget stopped the walk early; the result is then partial
    and must be labelled as such. Out-of-scope nodes never appear, not even as path
    intermediates.
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[CatalogEntity]
    edges: list[PresentedEdge]
    paths: list[GraphPath] = Field(default_factory=list)
    truncated: bool = False
    truncated_reason: Literal["max_nodes", "max_edges", "max_depth", "timeout_ms"] | None = None
    visited_nodes: Annotated[StrictInt, Field(ge=0)] = 0
    visited_edges: Annotated[StrictInt, Field(ge=0)] = 0


GraphView = Literal["presented", "raw"]


class GraphSearchRequest(BaseModel):
    """Term plus allowlisted entity filter plus mandatory budget."""

    model_config = ConfigDict(extra="forbid")

    term: Annotated[StrictStr, Field(max_length=256)]
    filters: EntityFilter = Field(default_factory=EntityFilter)
    budget: Budget


class NeighborsRequest(BaseModel):
    """Neighbors of one node, bounded by ``budget`` (depth, nodes, edges, time)."""

    model_config = ConfigDict(extra="forbid")

    node_id: CanonicalIdStr
    direction: Direction = "both"
    filters: EdgeFilter = Field(default_factory=EdgeFilter)
    budget: Budget
    view: GraphView = "presented"
    """``raw`` shows observed edges with no curation and is Auditor scope only."""


class ImpactRequest(BaseModel):
    """Bounded impact analysis: paths reachable from ``node_id`` (downstream = edges out)."""

    model_config = ConfigDict(extra="forbid")

    node_id: CanonicalIdStr
    direction: Literal["downstream", "upstream"] = "downstream"
    filters: EdgeFilter = Field(default_factory=EdgeFilter)
    budget: Budget
    view: GraphView = "presented"


@runtime_checkable
class GraphQuery(Protocol):
    """Bounded graph reads over a ``CatalogRepository``. Not a graph query engine."""

    async def get(self, scope: IdentityScope, node_id: str) -> CatalogEntity | None:
        """A node, or None when missing or out of scope."""
        ...

    async def search(self, scope: IdentityScope, request: GraphSearchRequest) -> GraphResult:
        """Entities in scope matching the term (nodes only; ``edges`` is empty)."""
        ...

    async def neighbors(self, scope: IdentityScope, request: NeighborsRequest) -> GraphResult:
        """Bounded walk to ``budget.max_depth``. Over budget returns the partial result with
        ``truncated=True``, never an unbounded walk. ``view="raw"`` raises ``ForbiddenError``
        unless the scope is an Auditor scope for the node's domain. Hidden (rejected) edges
        are omitted from the presented view.
        """
        ...

    async def impact_paths(self, scope: IdentityScope, request: ImpactRequest) -> GraphResult:
        """Bounded paths from a node; same budget, truncation and view rules as ``neighbors``.
        A path never passes through a node outside the scope.
        """
        ...
