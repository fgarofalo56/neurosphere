"""The catalog repository rules, written once over a ``DocBackend`` (PRP-10 item 1).

``CosmosCatalogRepository`` and ``InMemoryCatalogRepository`` are this engine plus a backend,
so they share one implementation of: scope enforcement, ETag concurrency, alias uniqueness,
append-only evidence, immutable overrides and the Auditor gate.

Scope enforcement. Every read builds its ``ScopeFilter`` from the ``IdentityScope`` (cloud,
customer, allowed domains) and the backend applies it server-side as part of the query. The
engine never reads a document and filters afterwards. Out-of-scope documents therefore look
exactly like missing ones. Writes compare the document's own cloud/customer/domain with the
scope and raise ``ForbiddenError``. ``domain_id`` and ``customer_id`` inside a caller-supplied
document are only ever compared to the scope, never trusted.

Two deliberate exceptions use an unscoped-by-domain existence check (cloud and customer
still apply): ID uniqueness on create (entity, edge, observation) and alias-key uniqueness. A
duplicate ID or alias key in another domain of the same customer would make an ID resolve in
two places, so it is refused; the refusal reveals only that the ID is taken.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from neurosphere_contracts.catalog.v1.alias import Alias
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride

from neurosphere_core.catalog.partitioning import DEFAULT_SHARD_COUNT, PartitionKeyShape
from neurosphere_core.catalog.protocol import (
    MAX_EDGES_PER_OVERRIDE_BATCH,
    MAX_OVERRIDES_PER_EDGE,
    AliasKey,
    CatalogEdge,
    CatalogEntity,
    Direction,
    EdgeFilter,
    EdgeObservation,
    EntityFilter,
)
from neurosphere_core.catalog.repo import documents as docs
from neurosphere_core.catalog.repo.backend import (
    DocBackend,
    DocConflictError,
    DocPreconditionFailedError,
    DocType,
    Field,
    Query,
    ScopeFilter,
)
from neurosphere_core.catalog.rules import format_timestamp
from neurosphere_core.errors.taxonomy import ForbiddenError, InvalidSchemaError, StaleVersionError
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

AUDITOR_ROLE = "security_auditor"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def require_scope(scope: object) -> IdentityScope:
    """Runtime half of "every query requires an IdentityScope" (the type half is pyright)."""
    if not isinstance(scope, IdentityScope):
        raise TypeError("an IdentityScope is required as the first argument")
    return scope


def _alias_eq(key: AliasKey) -> tuple[tuple[Field, str], ...]:
    return (
        ("alias_source_id", key.alias_source_id),
        ("alias_kind", key.alias_kind),
        ("alias_value", key.alias_value),
        ("alias_status", "active"),
    )


def new_etag() -> str:
    return uuid.uuid4().hex


class CatalogEngine:
    """Implements ``CatalogRepository`` over a ``DocBackend``."""

    def __init__(
        self,
        backend: DocBackend,
        shape: PartitionKeyShape = PartitionKeyShape.FLAT_DOMAIN,
        *,
        shard_count: int = DEFAULT_SHARD_COUNT,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._backend = backend
        self._shape = shape
        self._shard_count = shard_count
        self._clock = clock

    # ----------------------------------------------------------------- shared helpers

    @property
    def shape(self) -> PartitionKeyShape:
        """The effective partition key shape documents are written with."""
        return self._shape

    @staticmethod
    def _filter(scope: IdentityScope, domains: tuple[str, ...] | None = None) -> ScopeFilter:
        """Scope predicate. ``domains`` may only NARROW the scope's allowed domains."""
        allowed = scope.allowed_domains
        if domains is not None:
            allowed = tuple(d for d in dict.fromkeys(domains) if d in allowed)
        return ScopeFilter(scope.cloud, scope.customer_id, allowed)

    @staticmethod
    def _check_write(scope: IdentityScope, cloud: str, customer_id: str, domain_id: str) -> None:
        if (
            cloud != scope.cloud
            or customer_id != scope.customer_id
            or domain_id not in scope.allowed_domains
        ):
            raise ForbiddenError("the target is outside the caller's scope")

    async def _find(
        self,
        scope: IdentityScope,
        doc_type: DocType,
        ref: str,
        *,
        scoped: bool = True,
    ) -> dict[str, Any] | None:
        flt = self._filter(scope) if scoped else ScopeFilter(scope.cloud, scope.customer_id, None)
        if flt.domains is not None and not flt.domains:
            return None
        rows = await self._backend.query(Query(doc_type, flt, 1, eq=(("ref", ref),)))
        return dict(rows[0]) if rows else None

    def _doc(self, doc_type: DocType, ref: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
        return docs.make_doc(self._shape, doc_type, ref, body, shard_count=self._shard_count, **kw)

    async def _insert(self, doc: dict[str, Any]) -> bool:
        try:
            await self._backend.insert(doc)
        except DocConflictError:
            return False
        return True

    async def _replace(self, doc: dict[str, Any], stored: dict[str, Any]) -> None:
        try:
            await self._backend.replace(doc, stored["_etag"])
        except DocPreconditionFailedError as exc:
            raise StaleVersionError("the document changed since it was read") from exc

    @staticmethod
    def _page_args(page: PageRequest) -> tuple[int, str | None]:
        after = docs.decode_cursor(page.cursor) if page.cursor is not None else None
        return page.page_size + 1, after

    @staticmethod
    def _split(
        rows: Sequence[dict[str, Any]], size: int, key: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        kept = list(rows[:size])
        more = len(rows) > size
        return kept, (docs.encode_cursor(str(kept[-1][key])) if more and kept else None)

    # ----------------------------------------------------------------- entities

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        scope = require_scope(scope)
        docs.id_segments(entity_id)
        row = await self._find(scope, "entity", entity_id)
        return docs.parse_entity(row["body"]) if row else None

    def _entity_parts(self, entity: CatalogEntity) -> tuple[dict[str, Any], str]:
        body = docs.revalidate_entity(entity)
        domain = docs.entity_domain(body)
        if domain is None:
            raise InvalidSchemaError(
                "the entity has no domain_id; every catalog entity must belong to a domain"
            )
        docs.check_id(
            str(body["id"]),
            cloud=str(body["cloud"]),
            customer_id=str(body["customer_id"]),
            type_segment=str(body["entity_type"]),
        )
        return body, domain

    def _entity_doc(self, body: dict[str, Any], domain: str) -> dict[str, Any]:
        return self._doc(
            "entity",
            str(body["id"]),
            body,
            cloud=str(body["cloud"]),
            customer_id=str(body["customer_id"]),
            domain_id=domain,
            filters={
                "entity_type": str(body["entity_type"]),
                "lifecycle_status": str(body["lifecycle_status"]),
            },
        )

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        scope = require_scope(scope)
        body, domain = self._entity_parts(entity)
        self._check_write(scope, str(body["cloud"]), str(body["customer_id"]), domain)
        ref = str(body["id"])
        if await self._find(scope, "entity", ref, scoped=False) is not None:
            raise InvalidSchemaError("an entity with this ID already exists")
        body["version"] = 1
        body["etag"] = new_etag()
        saved = docs.parse_entity(body)
        if not await self._insert(self._entity_doc(body, domain)):
            raise InvalidSchemaError("an entity with this ID already exists")
        return saved

    async def update_entity(
        self, scope: IdentityScope, entity: CatalogEntity, expected_etag: str
    ) -> CatalogEntity:
        scope = require_scope(scope)
        body, domain = self._entity_parts(entity)
        self._check_write(scope, str(body["cloud"]), str(body["customer_id"]), domain)
        stored = await self._find(scope, "entity", str(body["id"]))
        if stored is None:
            raise InvalidSchemaError("the entity does not exist")
        current = stored["body"]
        if current["etag"] != expected_etag:
            raise StaleVersionError("the entity changed since it was read")
        if current["entity_type"] != body["entity_type"] or stored["domain_id"] != domain:
            raise InvalidSchemaError("entity_type and domain_id are immutable")
        body["created_at"] = current["created_at"]
        return await self._write_entity(stored, body, domain, int(current["version"]) + 1)

    async def deprecate_entity(
        self, scope: IdentityScope, entity_id: str, expected_etag: str
    ) -> CatalogEntity:
        scope = require_scope(scope)
        docs.id_segments(entity_id)
        stored = await self._find(scope, "entity", entity_id)
        if stored is None:
            raise InvalidSchemaError("the entity does not exist")
        body = dict(stored["body"])
        if body["etag"] != expected_etag:
            raise StaleVersionError("the entity changed since it was read")
        body["lifecycle_status"] = "deprecated"
        body["updated_at"] = format_timestamp(self._clock())
        return await self._write_entity(stored, body, stored["domain_id"], int(body["version"]) + 1)

    async def _write_entity(
        self, stored: dict[str, Any], body: dict[str, Any], domain: str, version: int
    ) -> CatalogEntity:
        body["version"] = version
        body["etag"] = new_etag()
        saved = docs.parse_entity(body)
        await self._replace(self._entity_doc(body, domain), stored)
        return saved

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        scope = require_scope(scope)
        narrowed = self._filter(
            scope, tuple(flt.domain_ids) if flt.domain_ids is not None else None
        )
        if not narrowed.domains:
            return Page[CatalogEntity](items=())
        limit, after = self._page_args(page)
        any_of: list[tuple[Field, tuple[str, ...]]] = []
        if flt.entity_types is not None:
            any_of.append(("entity_type", tuple(flt.entity_types)))
        if flt.lifecycle_statuses is not None:
            any_of.append(("lifecycle_status", tuple(flt.lifecycle_statuses)))
        rows = await self._backend.query(
            Query("entity", narrowed, limit, any_of=tuple(any_of), order="ref", after=after)
        )
        kept, cursor = self._split(rows, page.page_size, "ref")
        return Page[CatalogEntity](
            items=tuple(docs.parse_entity(r["body"]) for r in kept), next_cursor=cursor
        )

    # ----------------------------------------------------------------- aliases

    async def put_alias(self, scope: IdentityScope, alias: Alias) -> Alias:
        scope = require_scope(scope)
        body = docs.dump(alias)
        parsed = docs.validate_model(Alias, body)
        cloud, customer = parsed.cloud.root, parsed.customer_id.root
        if cloud != scope.cloud or customer != scope.customer_id:
            raise ForbiddenError("the target is outside the caller's scope")
        docs.check_id(parsed.id, cloud=cloud, customer_id=customer, type_segment="alias")
        docs.check_id(
            parsed.canonical_id, cloud=cloud, customer_id=customer, type_segment=parsed.entity_type
        )
        target = await self._find(scope, "entity", parsed.canonical_id)
        if target is None:
            # Missing and out-of-scope targets are indistinguishable by design.
            raise ForbiddenError("the alias target is not available in the caller's scope")
        domain = str(target["domain_id"])
        key = AliasKey(
            alias_source_id=parsed.alias_source_id.root,
            alias_kind=parsed.alias_kind,
            alias_value=parsed.alias_value,
        )
        own = await self._find(scope, "alias", parsed.id)
        if own is not None:
            return await self._update_alias(own, body, domain)
        if parsed.status == "active":
            clashes = await self._active_aliases(cloud, customer, key)
            if clashes:
                if all(c["body"]["canonical_id"] == parsed.canonical_id for c in clashes):
                    return Alias.model_validate(clashes[0]["body"])  # idempotent for the mapping
                raise InvalidSchemaError("the alias already resolves to a different canonical ID")
        body["version"] = 1
        body["etag"] = new_etag()
        saved = Alias.model_validate(body)
        if not await self._insert(self._alias_doc(body, domain)):
            raise InvalidSchemaError("an alias with this ID already exists")
        return saved

    def _alias_doc(self, body: dict[str, Any], domain: str) -> dict[str, Any]:
        alias = Alias.model_validate(body)
        return self._doc(
            "alias",
            alias.id,
            body,
            cloud=alias.cloud.root,
            customer_id=alias.customer_id.root,
            domain_id=domain,
            filters=docs.alias_filters(alias),
        )

    async def _update_alias(
        self, stored: dict[str, Any], body: dict[str, Any], domain: str
    ) -> Alias:
        current = stored["body"]
        if body["etag"] != current["etag"]:
            raise StaleVersionError("the alias changed since it was read")
        if body["canonical_id"] != current["canonical_id"] or stored["domain_id"] != domain:
            raise InvalidSchemaError("an alias cannot be re-pointed; retire it and add a new one")
        body["created_at"] = current["created_at"]
        body["version"] = int(current["version"]) + 1
        body["etag"] = new_etag()
        saved = Alias.model_validate(body)
        key = AliasKey(
            alias_source_id=saved.alias_source_id.root,
            alias_kind=saved.alias_kind,
            alias_value=saved.alias_value,
        )
        if saved.status == "active":
            clashes = await self._active_aliases(saved.cloud.root, saved.customer_id.root, key)
            if any(c["ref"] != stored["ref"] for c in clashes):
                raise InvalidSchemaError("the alias already resolves to a different canonical ID")
        await self._replace(self._alias_doc(body, domain), stored)
        return saved

    async def _active_aliases(
        self, cloud: str, customer_id: str, key: AliasKey
    ) -> list[dict[str, Any]]:
        """Active alias documents for ``key`` anywhere in the customer (uniqueness check)."""
        rows = await self._backend.query(
            Query(
                "alias",
                ScopeFilter(cloud, customer_id, None),
                2,
                eq=_alias_eq(key),
                order="ref",
            )
        )
        return [dict(r) for r in rows]

    async def resolve_alias(self, scope: IdentityScope, key: AliasKey) -> str | None:
        scope = require_scope(scope)
        flt = self._filter(scope)
        if not flt.domains:
            return None
        rows = await self._backend.query(
            Query(
                "alias",
                flt,
                1,
                eq=_alias_eq(key),
                order="ref",
            )
        )
        return str(rows[0]["body"]["canonical_id"]) if rows else None

    # ----------------------------------------------------------------- edges

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        scope = require_scope(scope)
        docs.id_segments(edge_id)
        row = await self._find(scope, "edge", edge_id)
        return docs.parse_edge(row["body"]) if row else None

    def _edge_doc(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._doc(
            "edge",
            str(body["id"]),
            body,
            cloud=str(body["cloud"]),
            customer_id=str(body["customer_id"]),
            domain_id=str(body["domain_id"]),
            filters={
                "relation_type": str(body["relation_type"]),
                "edge_status": str(body["status"]),
                "source_ref": str(body["source_id"]),
                "target_ref": str(body["target_id"]),
            },
        )

    @staticmethod
    def _validate_edge(body: dict[str, Any]) -> None:
        docs.check_id(
            str(body["id"]),
            cloud=str(body["cloud"]),
            customer_id=str(body["customer_id"]),
            type_segment=str(body["relation_type"]),
        )
        evidence = set(body["evidence_ids"])
        if body["status"] == "inferred" and not evidence:
            raise InvalidSchemaError("an inferred edge needs evidence IDs")
        if not set(body["security_evidence_ids"]) <= evidence:
            raise InvalidSchemaError("security_evidence_ids must be a subset of evidence_ids")

    async def put_edge(
        self, scope: IdentityScope, edge: CatalogEdge, expected_etag: str | None
    ) -> CatalogEdge:
        scope = require_scope(scope)
        body = docs.revalidate_edge(edge)
        self._validate_edge(body)
        domain = str(body["domain_id"])
        self._check_write(scope, str(body["cloud"]), str(body["customer_id"]), domain)
        ref = str(body["id"])
        if expected_etag is None:
            if await self._find(scope, "edge", ref, scoped=False) is not None:
                raise StaleVersionError("the edge already exists")
            body["version"] = 1
            body["etag"] = new_etag()
            saved = docs.parse_edge(body)
            if not await self._insert(self._edge_doc(body)):
                raise StaleVersionError("the edge already exists")
            return saved
        stored = await self._find(scope, "edge", ref)
        if stored is None:
            raise InvalidSchemaError("the edge does not exist")
        current = stored["body"]
        if current["etag"] != expected_etag:
            raise StaleVersionError("the edge changed since it was read")
        if current["relation_type"] != body["relation_type"] or current["domain_id"] != domain:
            raise InvalidSchemaError("relation_type and domain_id are immutable")
        if not (
            set(current["evidence_ids"]) <= set(body["evidence_ids"])
            and set(current["security_evidence_ids"]) <= set(body["security_evidence_ids"])
        ):
            raise InvalidSchemaError("evidence is append-only; a new version cannot drop any")
        body["created_at"] = current["created_at"]
        body["version"] = int(current["version"]) + 1
        body["etag"] = new_etag()
        saved = docs.parse_edge(body)
        await self._replace(self._edge_doc(body), stored)
        return saved

    async def list_edges_by_node(
        self,
        scope: IdentityScope,
        node_id: str,
        direction: Direction,
        flt: EdgeFilter,
        page: PageRequest,
    ) -> Page[CatalogEdge]:
        scope = require_scope(scope)
        docs.id_segments(node_id)
        scoped = self._filter(scope)
        if not scoped.domains or await self._find(scope, "entity", node_id) is None:
            return Page[CatalogEdge](items=())
        either: list[tuple[Field, str]] = []
        if direction in ("out", "both"):
            either.append(("source_ref", node_id))
        if direction in ("in", "both"):
            either.append(("target_ref", node_id))
        any_of: list[tuple[Field, tuple[str, ...]]] = []
        if flt.relation_types is not None:
            any_of.append(("relation_type", tuple(flt.relation_types)))
        if flt.statuses is not None:
            any_of.append(("edge_status", tuple(flt.statuses)))
        limit, after = self._page_args(page)
        rows = await self._backend.query(
            Query(
                "edge",
                scoped,
                limit,
                any_of=tuple(any_of),
                either=tuple(either),
                order="ref",
                after=after,
            )
        )
        kept, cursor = self._split(rows, page.page_size, "ref")
        return Page[CatalogEdge](
            items=tuple(docs.parse_edge(r["body"]) for r in kept), next_cursor=cursor
        )

    # ----------------------------------------------------------------- observations

    async def record_observation(self, scope: IdentityScope, observation: EdgeObservation) -> bool:
        scope = require_scope(scope)
        body = docs.dump(observation)
        parsed = docs.validate_model(EdgeObservation, body)
        docs.check_evidence_id(parsed.id)
        docs.check_id(parsed.edge_id, cloud=parsed.cloud, customer_id=parsed.customer_id)
        self._check_write(scope, parsed.cloud, parsed.customer_id, parsed.domain_id)
        if await self._find(scope, "observation", parsed.id, scoped=False) is not None:
            return False
        doc = self._doc(
            "observation",
            parsed.id,
            body,
            cloud=parsed.cloud,
            customer_id=parsed.customer_id,
            domain_id=parsed.domain_id,
            filters={"edge_ref": parsed.edge_id},
            sort_key=docs.observation_sort_key(parsed),
        )
        return await self._insert(doc)

    def _auditor_domains(self, scope: IdentityScope) -> tuple[str, ...]:
        now = self._clock()
        granted: dict[str, None] = {}
        for assignment in scope.to_contract().roles:
            if assignment.role != AUDITOR_ROLE:
                continue
            if docs.is_expired(assignment.expires_at.root if assignment.expires_at else None, now):
                continue
            for domain in assignment.domain_ids:
                granted.setdefault(domain.root)
        return tuple(d for d in scope.allowed_domains if d in granted)

    async def list_observations(
        self, scope: IdentityScope, edge_id: str, page: PageRequest
    ) -> Page[EdgeObservation]:
        scope = require_scope(scope)
        docs.id_segments(edge_id)
        auditor = self._auditor_domains(scope)
        if not auditor:
            raise ForbiddenError("raw observations require a security auditor scope")
        edge = await self._find(scope, "edge", edge_id)
        if edge is not None and str(edge["domain_id"]) not in auditor:
            raise ForbiddenError("raw observations require a security auditor scope")
        domains = (str(edge["domain_id"]),) if edge is not None else auditor
        limit, after = self._page_args(page)
        rows = await self._backend.query(
            Query(
                "observation",
                self._filter(scope, domains),
                limit,
                eq=(("edge_ref", edge_id),),
                order="sort_key",
                descending=True,
                after=after,
            )
        )
        kept, cursor = self._split(rows, page.page_size, "sort_key")
        return Page[EdgeObservation](
            items=tuple(EdgeObservation.model_validate(r["body"]) for r in kept),
            next_cursor=cursor,
        )

    # ----------------------------------------------------------------- overrides

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        scope = require_scope(scope)
        body = docs.dump(override)
        parsed = docs.validate_model(EdgeOverride, body)
        cloud, customer, domain = parsed.cloud.root, parsed.customer_id.root, parsed.domain_id.root
        docs.check_id(parsed.id, cloud=cloud, customer_id=customer, type_segment="edge_override")
        docs.check_id(
            parsed.edge_id,
            cloud=cloud,
            customer_id=customer,
            type_segment=parsed.relation_type.root,
        )
        self._check_write(scope, cloud, customer, domain)
        existing = await self._find(scope, "override", parsed.id)
        if existing is not None:
            if existing["body"] == body:
                return EdgeOverride.model_validate(existing["body"])
            raise InvalidSchemaError("overrides are immutable; this ID holds a different decision")
        edge = await self._find(scope, "edge", parsed.edge_id)
        if edge is None or str(edge["domain_id"]) != domain:
            raise InvalidSchemaError("the edge does not exist")
        current = edge["body"]
        if (
            current["etag"] != parsed.expected_edge_etag.root
            or int(current["version"]) != parsed.expected_edge_version.root
        ):
            raise StaleVersionError("the edge changed since the decision was prepared")
        doc = self._doc(
            "override",
            parsed.id,
            body,
            cloud=cloud,
            customer_id=customer,
            domain_id=domain,
            filters={"edge_ref": parsed.edge_id},
            sort_key=docs.override_sort_key(parsed),
        )
        if not await self._insert(doc):
            raise InvalidSchemaError("overrides are immutable; this ID is already taken")
        return parsed

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        scope = require_scope(scope)
        docs.id_segments(edge_id)
        flt = self._filter(scope)
        if not flt.domains:
            return ()
        rows = await self._backend.query(
            Query(
                "override",
                flt,
                MAX_OVERRIDES_PER_EDGE,
                eq=(("edge_ref", edge_id),),
                order="sort_key",
            )
        )
        return tuple(EdgeOverride.model_validate(r["body"]) for r in rows)

    async def list_overrides_for_edges(
        self, scope: IdentityScope, edge_ids: Sequence[str]
    ) -> dict[str, tuple[EdgeOverride, ...]]:
        scope = require_scope(scope)
        wanted = tuple(dict.fromkeys(edge_ids))
        if len(wanted) > MAX_EDGES_PER_OVERRIDE_BATCH:
            raise InvalidSchemaError(
                f"at most {MAX_EDGES_PER_OVERRIDE_BATCH} edge IDs per override batch"
            )
        for edge_id in wanted:
            docs.id_segments(edge_id)
        flt = self._filter(scope)
        if not wanted or not flt.domains:
            return {}
        edges = await self._backend.query(
            Query("edge", flt, len(wanted), any_of=(("ref", wanted),), order="ref")
        )
        grouped: dict[str, list[EdgeOverride]] = {str(e["ref"]): [] for e in edges}
        rows = await self._backend.query(
            Query(
                "override",
                flt,
                MAX_OVERRIDES_PER_EDGE * len(wanted),
                any_of=(("edge_ref", wanted),),
                order="sort_key",
            )
        )
        for row in rows:
            bucket = grouped.setdefault(str(row["body"]["edge_id"]), [])
            if len(bucket) < MAX_OVERRIDES_PER_EDGE:
                bucket.append(EdgeOverride.model_validate(row["body"]))
        return {edge_id: tuple(items) for edge_id, items in grouped.items()}
