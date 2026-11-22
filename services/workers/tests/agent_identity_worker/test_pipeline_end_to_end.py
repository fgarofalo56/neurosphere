"""PRP-137 item 7: OTLP spans through the real pipeline reach the right agent's series.

map_span -> process_batch -> archive fake -> outbox -> AggregateProjection + CatalogProjection on
a ResolvingTraceEventSource. No event is built with a canonical id.
"""

from __future__ import annotations

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import derive_agent_id
from neurosphere_core.catalog import EdgeFilter
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.agent_identity import reresolve_external_id

from .pipeline_support import (
    CLOUD,
    CUSTOMER,
    NOW,
    SOURCE,
    World,
    agent_id,
    make_world,
    map_document,
    model_call_span,
    otlp_document,
)

EXTERNAL = "support-bot"
DERIVED = derive_agent_id(CLOUD, CUSTOMER, SOURCE, EXTERNAL)
REAL = agent_id("support-bot")
SINKS = 2  # aggregates and catalog each resolve every event through the shared resolver


def events_for(*agents: str | None) -> list:  # type: ignore[type-arg]
    spans = [model_call_span(i, a) for i, a in enumerate(agents)]
    return map_document(otlp_document(spans))


async def run(world: World, *agents: str | None) -> None:
    mapped = events_for(*agents)
    # the mapping alone never sets a canonical id: that is what the resolver is for
    assert all(e.canonical_agent_id is None for e in mapped)
    await world.ingest(mapped)
    assert not world.harness.quarantine.effects
    await world.drain()


async def uses_model_sources(world: World) -> set[str]:
    edges = await world.edges(EdgeFilter(relation_types=["uses_model"]))
    return {e.source_id for e in edges}


async def test_alias_present_counts_for_the_aliased_agent() -> None:
    world = await make_world(aliases=[(EXTERNAL, "support-bot")])
    await run(world, EXTERNAL, EXTERNAL)

    assert world.agent_events(REAL) == 2
    assert world.agent_events(DERIVED) == 0
    assert REAL in await uses_model_sources(world)
    assert world.resolver.stats.resolved_alias == 2 * SINKS
    assert world.catalog.stats.agent_drafts_created == 0


async def test_no_alias_uses_derived_id_and_creates_a_draft() -> None:
    world = await make_world()
    await run(world, EXTERNAL, EXTERNAL)

    assert world.agent_events(DERIVED) == 2
    assert len(world.harness.archive.effects) == 2  # nothing dropped
    assert not world.harness.quarantine.effects
    assert world.catalog.quarantine is not None
    drafts = [a for a in await world.agents() if a.id == DERIVED]
    assert len(drafts) == 1
    attrs = drafts[0].attributes
    assert attrs is not None
    assert attrs.root["discovered_from"] == "telemetry"
    assert attrs.root["agent_identity"] == "derived_from_external_id"
    assert drafts[0].external_agent_id is not None
    assert drafts[0].external_agent_id.root == EXTERNAL
    assert DERIVED in await uses_model_sources(world)
    assert world.resolver.stats.derived == 2 * SINKS


async def test_alias_added_later_reresolve_moves_contributions() -> None:
    world = await make_world()
    await run(world, EXTERNAL, EXTERNAL, EXTERNAL)
    assert world.agent_events(DERIVED) == 3

    await world.declare(EXTERNAL, "support-bot")
    world.clock.now += 1000  # past the negative cache TTL
    args = {
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "external_agent_id": EXTERNAL,
        "reader": world.reader,
        "aggregates": world.aggregates,
        "store": world.store,
        "catalog": world.catalog,
        "max_events": 100,
        "resolver_stats": world.resolver.stats,
        "clock": lambda: NOW,
    }
    report = await reresolve_external_id(**args)  # type: ignore[arg-type]
    assert report.moved == 3

    assert world.agent_events(REAL) == 3
    assert world.agent_events(DERIVED) == 0
    assert f"agent:{DERIVED}" not in world.series_keys()  # old series points are gone

    fresh = await make_world(aliases=[(EXTERNAL, "support-bot")])
    await run(fresh, EXTERNAL, EXTERNAL, EXTERNAL)
    after_first = world.snapshot()
    assert after_first["contributions"] == fresh.snapshot()["contributions"]
    assert {k: v for k, v in after_first["docs"].items() if "agent:" in v["series_key"]} == {
        k: v for k, v in fresh.snapshot()["docs"].items() if "agent:" in v["series_key"]
    }
    assert after_first["docs"] == fresh.snapshot()["docs"]

    second = await reresolve_external_id(**args)  # type: ignore[arg-type]
    assert second.moved == 0
    assert world.snapshot() == after_first


async def test_external_ids_that_slug_alike_stay_distinct() -> None:
    world = await make_world()
    await run(world, "Bot One", "bot-one", "bot-one")
    first = derive_agent_id(CLOUD, CUSTOMER, SOURCE, "Bot One")
    second = derive_agent_id(CLOUD, CUSTOMER, SOURCE, "bot-one")
    assert first != second
    assert world.agent_events(first) == 1
    assert world.agent_events(second) == 2
    ids = {a.id for a in await world.agents()}
    assert {first, second} <= ids


@pytest.mark.parametrize(
    "target",
    [
        f"commercial:other:foundry:agent:{EXTERNAL}",  # another customer
        f"government:{CUSTOMER}:foundry:agent:{EXTERNAL}",  # another cloud
        f"commercial:{CUSTOMER}:foundry:tool:{EXTERNAL}",  # not an agent
    ],
)
async def test_invalid_alias_target_is_ignored_and_counted(target: str) -> None:
    world = await make_world()
    world.lookup.overrides[EXTERNAL] = target  # a backend that hands out a foreign target
    await run(world, EXTERNAL, EXTERNAL)

    assert world.resolver.stats.alias_target_invalid == 2 * SINKS
    assert world.agent_events(DERIVED) == 2
    assert world.agent_events(target) == 0
    assert all(CUSTOMER in key and CLOUD in key for key in world.series_keys() if "agent:" in key)
    assert target not in {a.id for a in await world.agents()}


async def test_lookup_outage_retries_and_writes_no_derived_series() -> None:
    world = await make_world()
    world.lookup.down = True
    await world.ingest(events_for(EXTERNAL))
    with pytest.raises(DependencyTransientError):
        await world.drain()
    assert not any("agent:" in key for key in world.series_keys())
    assert world.store.contributions(CUSTOMER) == {}
    assert world.resolver.stats.lookup_failures >= 1

    world.lookup.down = False  # the retry succeeds and files it under the right agent
    await world.drain()
    assert world.agent_events(DERIVED) == 1


async def test_event_with_no_agent_id_keeps_canonical_null() -> None:
    world = await make_world()
    await run(world, None)
    assert world.resolver.stats.no_agent_id == SINKS
    assert not any(key.startswith("agent:") for key in world.series_keys())
    assert not any(a.id == DERIVED for a in await world.agents())
    assert world.catalog.stats.agent_drafts_created == 0


async def test_event_with_owned_canonical_id_is_declared_and_unchanged() -> None:
    world = await make_world(target_names=("support-bot", "other"))
    events = [
        TelemetryEvent.model_validate(
            {**e.model_dump(mode="json"), "canonical_agent_id": agent_id("other")}
        )
        for e in events_for(EXTERNAL)
    ]
    await world.ingest(events)
    await world.drain()
    assert world.resolver.stats.declared == SINKS
    assert world.agent_events(agent_id("other")) == 1
    assert world.agent_events(DERIVED) == 0
