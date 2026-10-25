"""RecommendationStore conformance: in-memory and CosmosRecommendationStore on a fake container."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_core.recommendations import InMemoryRecommendationStore, RecommendationStore
from neurosphere_core.recommendations.cosmos_store import (
    DEFAULT_RECOMMENDATION_CONTAINER,
    RECOMMENDATION_PARTITION_KEY_PATHS,
    CosmosRecommendationStore,
)

from .conformance import CHECKS, FINANCE, OPERATIONS, make_scope, rec
from .cosmos_fake import new_container

BACKENDS: dict[str, Callable[[], RecommendationStore]] = {
    "memory": InMemoryRecommendationStore,
    "cosmos-fake": lambda: CosmosRecommendationStore(new_container()),  # type: ignore[arg-type]
}


@pytest.mark.parametrize("backend", sorted(BACKENDS))
@pytest.mark.parametrize("check", sorted(CHECKS))
async def test_conformance(backend: str, check: str) -> None:
    await CHECKS[check](BACKENDS[backend]())


def test_container_constants_match_the_wire_contract() -> None:
    assert DEFAULT_RECOMMENDATION_CONTAINER == "recommendations"
    assert RECOMMENDATION_PARTITION_KEY_PATHS == ("/customer_id", "/domain_id")


# -- Cosmos-specific: the scope filter is in every query ----------------------------------------


async def test_every_query_is_single_partition_and_carries_the_scope_predicates() -> None:
    container = new_container()
    store = CosmosRecommendationStore(container)  # type: ignore[arg-type]
    scope = make_scope([FINANCE])
    await store.put(rec(1))
    await store.list(scope, FINANCE)
    await store.list(scope, FINANCE, kind="cost_spike", q="spike", cursor=None, limit=3)
    assert len(container.queries) == 2
    for record in container.queries:
        assert record.partition_key == ("contoso", FINANCE)
        for predicate in ("c.customer_id = @customer", "c.domain_id = @domain", "c.cloud = @cloud"):
            assert predicate in record.query
        assert record.params["@customer"] == "contoso"
        assert record.params["@domain"] == FINANCE
        assert record.params["@cloud"] == "commercial"
        assert "TOP @limit" in record.query
    assert container.queries[1].params["@limit"] == 4  # limit + 1 to detect a next page


async def test_a_domain_outside_the_scope_never_reaches_cosmos() -> None:
    container = new_container()
    store = CosmosRecommendationStore(container)  # type: ignore[arg-type]
    scope = make_scope([FINANCE])
    await store.put(rec(1, domain=OPERATIONS))
    assert (await store.list(scope, OPERATIONS)).items == ()
    assert await store.get(scope, OPERATIONS, rec(1).recommendation_id.root) is None
    assert container.queries == []


async def test_same_id_in_two_customers_stays_separate_in_cosmos() -> None:
    store = CosmosRecommendationStore(new_container())  # type: ignore[arg-type]
    await store.put(rec(1, customer="contoso"))
    await store.put(rec(1, customer="fabrikam"))
    rid = rec(1).recommendation_id.root
    fabrikam = await store.get(make_scope([FINANCE], customer="fabrikam"), FINANCE, rid)
    contoso = await store.get(make_scope([FINANCE], customer="contoso"), FINANCE, rid)
    assert fabrikam is not None
    assert fabrikam.customer_id == "fabrikam"
    assert contoso is not None
    assert contoso.customer_id == "contoso"


async def test_a_tampered_document_fails_closed_as_upstream_invalid() -> None:
    container = new_container()
    store = CosmosRecommendationStore(container)  # type: ignore[arg-type]
    await store.put(rec(1))
    for doc in container.items.values():
        doc["kind"] = "not_a_kind"
    with pytest.raises(DependencyTransientError) as raised:
        await store.list(make_scope([FINANCE]), FINANCE)
    assert raised.value.reason == "recommendation_record_invalid"
    assert raised.value.status == 502


class _Failing:
    def __init__(self, status: int | None) -> None:
        self.status = status

    def _fail(self) -> Any:
        if self.status is None:
            raise ConnectionError("secret-host.example")
        raise CosmosHttpResponseError(status_code=self.status, message="boom secret")

    async def upsert_item(self, **_: Any) -> Any:
        self._fail()

    async def read_item(self, **_: Any) -> Any:
        self._fail()

    def query_items(self, *_: Any, **__: Any) -> Any:
        self._fail()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(None, DependencyTransientError), (503, DependencyTransientError), (429, RateLimitedError)],
)
async def test_outages_map_to_taxonomy_errors_without_echoing_sdk_text(
    status: int | None, expected: type[Exception]
) -> None:
    store = CosmosRecommendationStore(_Failing(status))  # type: ignore[arg-type]
    scope = make_scope([FINANCE])
    for call in (
        store.put(rec(1)),
        store.list(scope, FINANCE),
        store.get(scope, FINANCE, rec(1).recommendation_id.root),
    ):
        with pytest.raises(expected) as raised:
            await call
        assert "secret" not in str(raised.value)
