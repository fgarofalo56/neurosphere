"""Catalog repository: shared conformance on the in-memory repo, plus pure unit tests."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.grant import Grant
from neurosphere_contracts.catalog.v1.grants_access_to import GrantsAccessToRelation
from neurosphere_contracts.catalog.v1.mcp_server import McpServer
from neurosphere_contracts.catalog.v1.person import Person
from neurosphere_core.capabilities import default_matrix
from neurosphere_core.catalog import (
    CatalogRepository,
    EdgeFilter,
    EntityFilter,
    PartitionKeyShape,
    partition_key_paths,
    resolve_shape,
)
from neurosphere_core.catalog.repo import (
    InMemoryCatalogRepository,
    Query,
    ScopeFilter,
    require_scope,
)
from neurosphere_core.catalog.repo import documents as docs
from neurosphere_core.catalog.repo.cosmos import build_sql, partition_key_definition
from neurosphere_core.errors.taxonomy import InvalidSchemaError
from neurosphere_core.paging import PageRequest

from .repo_conformance import CHECKS, agent, dom, example, make_scope

SHAPES = [PartitionKeyShape.FLAT_DOMAIN, PartitionKeyShape.TENANT_DOMAIN_SHARD]


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.value)
@pytest.mark.parametrize("name", list(CHECKS))
async def test_in_memory_conformance(name: str, shape: PartitionKeyShape) -> None:
    repo = InMemoryCatalogRepository(shape)
    assert isinstance(repo, CatalogRepository)
    await CHECKS[name](repo, f"t{uuid.uuid4().hex[:10]}")


def test_default_shape_is_flat_with_current_matrix() -> None:
    resolution = resolve_shape(
        PartitionKeyShape.TENANT_DOMAIN_SHARD, "commercial", default_matrix()
    )
    assert resolution.fell_back
    definition = partition_key_definition(resolution.shape)
    assert definition["paths"] == ["/domain"]
    assert definition["kind"] == "Hash"


def test_hierarchical_key_definition_follows_the_shape() -> None:
    definition = partition_key_definition(PartitionKeyShape.TENANT_DOMAIN_SHARD)
    assert definition["paths"] == list(partition_key_paths(PartitionKeyShape.TENANT_DOMAIN_SHARD))
    assert definition["kind"] == "MultiHash"
    assert definition["version"] == 2


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.value)
async def test_documents_carry_exactly_the_key_fields_of_the_shape(
    shape: PartitionKeyShape,
) -> None:
    ns = f"t{uuid.uuid4().hex[:10]}"
    repo = InMemoryCatalogRepository(shape)
    scope = make_scope(ns, [dom(ns, "a")])
    created = await repo.create_entity(scope, agent(ns, "k1", "a"))
    rows = await repo._backend.query(
        Query("entity", ScopeFilter("commercial", ns, None), 10, eq=(("ref", created.id),))
    )
    names = [p.lstrip("/") for p in partition_key_paths(shape)]
    assert all(name in rows[0] for name in names)
    assert rows[0]["domain"] == dom(ns, "a")
    if shape is PartitionKeyShape.TENANT_DOMAIN_SHARD:
        assert rows[0]["tenant"] == ns
        assert len(rows[0]["shard"]) == 4


def test_slash_in_ids_is_encoded_for_cosmos() -> None:
    encoded = docs.storage_id("entity", "commercial:a:b:agent:x/y")
    assert "/" not in encoded
    assert encoded.startswith("entity:")


def test_sql_is_parameterized_and_scope_bound() -> None:
    hostile = "x' OR 1=1 --"
    sql, params = build_sql(
        Query(
            "entity",
            ScopeFilter("commercial", hostile, (hostile, "d2")),
            11,
            eq=(("ref", hostile),),
            any_of=(("entity_type", ("agent", hostile)),),
            either=(("source_ref", hostile), ("target_ref", hostile)),
            order="ref",
            after=hostile,
        )
    )
    assert hostile not in sql
    assert "ARRAY_CONTAINS(@p3, c.domain_id)" in sql
    assert "c.cloud = @p1" in sql
    assert "c.customer_id = @p2" in sql
    assert sql.startswith("SELECT TOP @p")
    assert "ORDER BY c.ref ASC" in sql
    assert {p["name"] for p in params} == {f"@p{i}" for i in range(len(params))}
    assert hostile in [p["value"] for p in params]


def test_query_rejects_fields_outside_the_allowlist() -> None:
    scope = ScopeFilter("commercial", "c", ())
    with pytest.raises(ValueError, match="allowlisted"):
        Query("entity", scope, 1, eq=(("c.id; DROP", "x"),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit"):
        Query("entity", scope, 0)


def test_require_scope_rejects_non_scopes() -> None:
    for bad in (None, object(), "scope", {"cloud": "commercial"}):
        with pytest.raises(TypeError):
            require_scope(bad)
    scope = make_scope("acme", [dom("acme", "a")])
    assert require_scope(scope) is scope


async def test_person_without_domain_is_refused() -> None:
    raw = example("person.minimal-and-typical.json")
    raw.update(
        domain_id=None, customer_id="acme", id="commercial:acme:entra:person:psn_0123456789abcdef"
    )
    repo = InMemoryCatalogRepository()
    with pytest.raises(InvalidSchemaError):
        await repo.create_entity(make_scope("acme", [dom("acme", "a")]), Person.model_validate(raw))


# --------------------------------------------------------------------------- PRP-33 item 5


def _rehome(name: str, ns: str) -> dict[str, Any]:
    """A golden catalog example moved into customer ``ns`` (every canonical ID and customer_id)."""
    text = json.dumps(example(name)).replace(":contoso:", f":{ns}:")
    raw = json.loads(text)
    raw["customer_id"] = ns
    raw["version"] = 1
    raw["etag"] = "caller-etag"
    return raw


GATEWAY_ENTITIES = [
    ("grant.user-model-deployment-token-limits.json", Grant),
    ("grant.entra-group-mcp-calls.json", Grant),
    ("mcp_server.entra-streamable-http.json", McpServer),
    ("mcp_server.api-key-not-publishable.json", McpServer),
]


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.value)
@pytest.mark.parametrize(("name", "model"), GATEWAY_ENTITIES, ids=[n for n, _ in GATEWAY_ENTITIES])
async def test_grant_and_mcp_server_entities_round_trip_through_the_store(
    name: str, model: type[Grant] | type[McpServer], shape: PartitionKeyShape
) -> None:
    ns = f"t{uuid.uuid4().hex[:10]}"
    repo = InMemoryCatalogRepository(shape)
    scope = make_scope(ns, [dom(ns, "finance")])
    entity = model.model_validate(_rehome(name, ns))
    created = await repo.create_entity(scope, entity)
    assert isinstance(created, model)
    assert created.version.root == 1 and created.etag.root != "caller-etag"
    got = await repo.get_entity(scope, entity.id)
    assert got == created
    expected = entity.model_dump(mode="json", exclude={"version", "etag"})
    assert created.model_dump(mode="json", exclude={"version", "etag"}) == expected
    listed = await repo.list_entities(
        scope, EntityFilter(entity_types=[entity.entity_type]), PageRequest()
    )
    assert [e.id for e in listed.items] == [entity.id]
    # out of scope reads as missing
    assert await repo.get_entity(make_scope(ns, [dom(ns, "other")]), entity.id) is None


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.value)
async def test_grants_access_to_edge_round_trips_through_the_store(
    shape: PartitionKeyShape,
) -> None:
    ns = f"t{uuid.uuid4().hex[:10]}"
    repo = InMemoryCatalogRepository(shape)
    scope = make_scope(ns, [dom(ns, "finance")])
    grant = Grant.model_validate(_rehome("grant.entra-group-mcp-calls.json", ns))
    server = McpServer.model_validate(_rehome("mcp_server.entra-streamable-http.json", ns))
    await repo.create_entity(scope, grant)
    await repo.create_entity(scope, server)
    edge = GrantsAccessToRelation.model_validate(_rehome("grants_access_to.asserted.json", ns))
    assert edge.source_id == grant.id and edge.target_id == server.id
    stored = await repo.put_edge(scope, edge, None)
    assert isinstance(stored, GrantsAccessToRelation)
    assert await repo.get_edge(scope, edge.id) == stored
    out = await repo.list_edges_by_node(
        scope, grant.id, "out", EdgeFilter(relation_types=["grants_access_to"]), PageRequest()
    )
    assert [e.id for e in out.items] == [edge.id]
    inn = await repo.list_edges_by_node(scope, server.id, "in", EdgeFilter(), PageRequest())
    assert [e.id for e in inn.items] == [edge.id]
