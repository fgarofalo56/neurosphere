"""ReviewQueue: idempotent, scope-filtered; and the protocols are scope-first."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Sequence

import pytest
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import (
    AliasKey,
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    EdgeFilter,
    EdgeObservation,
    EntityFilter,
    GraphQuery,
    GraphResult,
    GraphSearchRequest,
    ImpactRequest,
    InMemoryReviewQueue,
    NeighborsRequest,
    ReviewItem,
    ReviewQueue,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

FINANCE = "commercial:contoso:neurosphere:domain:finance"
RETAIL = "commercial:contoso:neurosphere:domain:retail"
EDGE = "commercial:contoso:neurosphere:invokes:e-0001"
PERSON = "commercial:contoso:entra:person:psn_0123456789abcdef"


def make_scope(domains: list[str]) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": PERSON,
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": domains,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_item(
    item_id: str = "review:one", domain: str = FINANCE, at: str = "2026-10-17T10:00:00Z"
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        edge_id=EDGE,
        relation_type="invokes",
        cloud="commercial",
        customer_id="contoso",
        domain_id=domain,
        reason="conflicts_with_lock",
        governing_override_id="commercial:contoso:neurosphere:edge_override:lock-1",
        observed_confidence=0.2,
        presented_confidence=0.82,
        new_evidence_ids=["trace:new-0001"],
        created_at=at,
    )


async def test_enqueue_is_idempotent_by_id() -> None:
    queue = InMemoryReviewQueue()
    scope = make_scope([FINANCE])
    assert await queue.enqueue(scope, make_item()) is True
    assert await queue.enqueue(scope, make_item()) is False
    assert len(await queue.list_open(scope)) == 1


async def test_out_of_scope_items_are_invisible_and_cannot_be_enqueued() -> None:
    queue = InMemoryReviewQueue()
    finance = make_scope([FINANCE])
    retail = make_scope([RETAIL])
    await queue.enqueue(finance, make_item())
    assert await queue.get(retail, "review:one") is None
    assert await queue.list_open(retail) == ()
    with pytest.raises(ForbiddenError):
        await queue.enqueue(retail, make_item("review:two"))
    with pytest.raises(ForbiddenError):
        await queue.resolve(
            retail,
            "review:one",
            resolved_by=PERSON,
            resolution="kept_curation",
            resolved_at="2026-10-17T11:00:00Z",
        )


async def test_resolve_closes_item_and_orders_by_age() -> None:
    queue = InMemoryReviewQueue()
    scope = make_scope([FINANCE])
    await queue.enqueue(scope, make_item("review:b", at="2026-10-17T10:00:00Z"))
    await queue.enqueue(scope, make_item("review:a", at="2026-10-17T09:00:00Z"))
    assert [i.id for i in await queue.list_open(scope)] == ["review:a", "review:b"]
    resolved = await queue.resolve(
        scope,
        "review:a",
        resolved_by=PERSON,
        resolution="accepted_inference",
        resolved_at="2026-10-17T11:00:00Z",
    )
    assert resolved.status == "resolved"
    assert [i.id for i in await queue.list_open(scope)] == ["review:b"]
    got = await queue.get(scope, "review:a")
    assert got is not None
    assert got.resolution == "accepted_inference"


async def test_stored_items_are_copies() -> None:
    queue = InMemoryReviewQueue()
    scope = make_scope([FINANCE])
    item = make_item()
    await queue.enqueue(scope, item)
    item.new_evidence_ids.append("tampered")
    got = await queue.get(scope, "review:one")
    assert got is not None
    assert got.new_evidence_ids == ["trace:new-0001"]


def test_in_memory_queue_satisfies_protocol() -> None:
    assert isinstance(InMemoryReviewQueue(), ReviewQueue)


# --------------------------------------------------------------------------- protocols


class _FakeRepo:
    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None:
        return None

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        return entity

    async def update_entity(
        self, scope: IdentityScope, entity: CatalogEntity, expected_etag: str
    ) -> CatalogEntity:
        return entity

    async def deprecate_entity(
        self, scope: IdentityScope, entity_id: str, expected_etag: str
    ) -> CatalogEntity:
        raise NotImplementedError

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]:
        return Page[CatalogEntity](items=())

    async def put_alias(self, scope: IdentityScope, alias: object) -> object:
        return alias

    async def resolve_alias(self, scope: IdentityScope, key: AliasKey) -> str | None:
        return None

    async def get_edge(self, scope: IdentityScope, edge_id: str) -> CatalogEdge | None:
        return None

    async def put_edge(
        self, scope: IdentityScope, edge: CatalogEdge, expected_etag: str | None
    ) -> CatalogEdge:
        return edge

    async def list_edges_by_node(
        self, scope: IdentityScope, node_id: str, direction: str, flt: EdgeFilter, page: PageRequest
    ) -> Page[CatalogEdge]:
        return Page[CatalogEdge](items=())

    async def record_observation(self, scope: IdentityScope, observation: EdgeObservation) -> bool:
        return True

    async def list_observations(
        self, scope: IdentityScope, edge_id: str, page: PageRequest
    ) -> Page[EdgeObservation]:
        return Page[EdgeObservation](items=())

    async def put_override(self, scope: IdentityScope, override: EdgeOverride) -> EdgeOverride:
        return override

    async def list_overrides(self, scope: IdentityScope, edge_id: str) -> tuple[EdgeOverride, ...]:
        return ()

    async def list_overrides_for_edges(
        self, scope: IdentityScope, edge_ids: Sequence[str]
    ) -> dict[str, tuple[EdgeOverride, ...]]:
        return {}


class _FakeGraph:
    async def get(self, scope: IdentityScope, node_id: str) -> CatalogEntity | None:
        return None

    async def search(self, scope: IdentityScope, request: GraphSearchRequest) -> GraphResult:
        return GraphResult(nodes=[], edges=[])

    async def neighbors(self, scope: IdentityScope, request: NeighborsRequest) -> GraphResult:
        return GraphResult(nodes=[], edges=[])

    async def impact_paths(self, scope: IdentityScope, request: ImpactRequest) -> GraphResult:
        return GraphResult(nodes=[], edges=[])


def test_fakes_satisfy_protocols() -> None:
    assert isinstance(_FakeRepo(), CatalogRepository)
    assert isinstance(_FakeGraph(), GraphQuery)


def test_incomplete_implementation_does_not_satisfy_protocol() -> None:
    class Partial:
        async def get_entity(self, scope: IdentityScope, entity_id: str) -> None:
            return None

    assert not isinstance(Partial(), CatalogRepository)


@pytest.mark.parametrize("proto", [CatalogRepository, GraphQuery])
def test_every_method_takes_a_required_scope_first(proto: type) -> None:
    methods = [
        name
        for name, member in vars(proto).items()
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    ]
    assert methods
    for name in methods:
        params = list(inspect.signature(getattr(proto, name)).parameters.values())
        assert params[0].name == "self"
        scope_param = params[1]
        assert scope_param.name == "scope", name
        assert scope_param.default is inspect.Parameter.empty, name
