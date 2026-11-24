"""Model delta node ids equal the viewport's model node ids (PRP-74 item 4, PRP-49 follow-up 2).

The aggregate source emits ``provider/model``; the gateway rewrites each model node to every
readable deployment id with a snapshot taken under the receiving session's scope.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import topology_helpers as th  # pyright: ignore[reportMissingImports]
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    pseudonymizer,
)
from neurosphere_api.map import ViewportLimits
from neurosphere_api.map.service import build_viewport
from neurosphere_api.map.settings import MapSettings
from neurosphere_api.map.topology import TopologySource
from neurosphere_api.realtime import RealtimeSettings
from neurosphere_api.realtime.source import AggregateDeltaSource, expand_model_nodes
from neurosphere_core.aggregates import (
    AggregateStatus,
    InMemoryAggregateStore,
    SubjectPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
)
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex

NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)
MODEL_KEY = "model:azure_openai/gpt-4o"


@dataclass
class World:
    repo: InMemoryCatalogRepository
    store: InMemoryAggregateStore
    alice: IdentityScope
    bob: IdentityScope


def _point(key: str, domain: str) -> SubjectPoint:
    start = format_bucket(bucket_start(NOW, "hour"))
    return SubjectPoint(
        id=aggregate_doc_id(CUSTOMER, domain, "subject", "hour", start, key),
        customer_id=CUSTOMER,
        domain_id=domain,
        grain="hour",
        bucket_start=start,
        series_key=key,
        watermark=start,
        complete=True,
        subject_kind="model",
        subject_key=key,
        event_count=9,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_count=0,
        error_rate=0.0,
        p95_ms=100,
    )


async def _world() -> World:
    h = th.harness(*th.policies())
    repo = InMemoryCatalogRepository()
    steward = await th.scope_of(h, th.STEWARD)
    await th.seed(
        repo,
        steward,
        th.agent_doc("a1"),
        th.model_doc("gpt-4o-east"),
        th.model_doc("gpt-4o-west"),
        th.model_doc("mini", model_name="gpt-4o-mini"),
        th.model_doc("ops-gpt", th.OPERATIONS),
    )
    store = InMemoryAggregateStore()
    start = format_bucket(bucket_start(NOW, "hour"))
    for domain in (th.FINANCE, th.OPERATIONS):
        await store.replace_bucket(CUSTOMER, domain, "hour", start, [_point(MODEL_KEY, domain)])
    await store.put_status(AggregateStatus(customer_id=CUSTOMER, watermark=start))
    return World(
        repo=repo,
        store=store,
        alice=await th.scope_of(h, th.ALICE),
        bob=await th.scope_of(h, th.BOB),
    )


async def test_delta_model_ids_equal_the_viewport_model_node_ids() -> None:
    w = await _world()
    source = AggregateDeltaSource(w.store, RealtimeSettings(), clock=lambda: 0.0)
    payload = await source.poll(CUSTOMER, th.FINANCE, NOW)
    assert [n.id for n in payload.nodes if n.kind == "model"] == ["azure_openai/gpt-4o"]

    topology = TopologySource(w.repo, MapSettings(), clock=lambda: 0.0)
    snapshot = await topology.snapshot(w.alice, th.FINANCE)
    mapped = expand_model_nodes(payload, snapshot.model_ids)

    viewport = await build_viewport(
        scope=w.alice,
        domain_id=th.FINANCE,
        cluster_id=None,
        cursor=None,
        node_budget=500,
        edge_budget=1000,
        repository=w.repo,
        graph=RepositoryGraphQuery(w.repo, FixtureSearchIndex([])),
        reader=w.store,
        pseudonymizer=pseudonymizer(),
        clock=lambda: NOW,
        limits=ViewportLimits(),
    )
    viewport_models = {n.id for n in viewport.nodes if n.kind == "model"}
    delta_models = {n.id for n in mapped.nodes if n.kind == "model"}
    assert delta_models == {
        "commercial:contoso:foundry:model_deployment:gpt-4o-east",
        "commercial:contoso:foundry:model_deployment:gpt-4o-west",
    }
    # Every delta model id is a viewport id (the mini deployment has no delta point).
    assert delta_models <= viewport_models
    assert {n.metrics.frequency for n in mapped.nodes if n.kind == "model"} == {9}
    assert [n.id for n in mapped.nodes if n.kind == "cluster"] == [th.FINANCE]


async def test_a_snapshot_under_an_unreadable_scope_yields_no_model_ids() -> None:
    w = await _world()
    source = AggregateDeltaSource(w.store, RealtimeSettings(), clock=lambda: 0.0)
    payload = await source.poll(CUSTOMER, th.OPERATIONS, NOW)
    assert any(n.kind == "model" for n in payload.nodes)
    topology = TopologySource(w.repo, MapSettings(), clock=lambda: 0.0)
    snapshot = await topology.snapshot(w.bob, th.OPERATIONS)  # Bob cannot read Operations
    assert snapshot.models == ()
    mapped = expand_model_nodes(payload, snapshot.model_ids)
    assert not [n for n in mapped.nodes if n.kind == "model"]


async def test_without_a_snapshot_no_model_node_is_sent() -> None:
    w = await _world()
    source = AggregateDeltaSource(w.store, RealtimeSettings(), clock=lambda: 0.0)
    payload = await source.poll(CUSTOMER, th.FINANCE, NOW)
    assert any(n.kind == "model" for n in payload.nodes)
    mapped = expand_model_nodes(payload, None)
    assert not [n for n in mapped.nodes if n.kind == "model"]
    assert [n.id for n in mapped.nodes] == [th.FINANCE]  # the domain node is untouched
