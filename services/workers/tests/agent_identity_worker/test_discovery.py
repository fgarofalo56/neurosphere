"""PRP-137 item 3: derived agents are surfaced as draft Agents by the catalog projection."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import derive_agent_id
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.paging import PageRequest
from neurosphere_workers.projections.catalog import LoadedEvent
from neurosphere_workers.projections.catalog.discovery import agent_discovery_entity
from projections.catalog_support import Rig, outbox_entry  # type: ignore[import-not-found]

from .fakes import CUSTOMER, doc

DOMAIN = f"commercial:{CUSTOMER}:sandbox:domain:dom-001"
OTHER_DOMAIN = f"commercial:{CUSTOMER}:sandbox:domain:dom-999"
EXTERNAL = "My Agent 1"
DERIVED = derive_agent_id("commercial", CUSTOMER, "sandbox-gateway", EXTERNAL)


def stamped(
    event_id: str,
    status: str | None = "derived",
    canonical: str | None = DERIVED,
    **overrides: Any,
) -> LoadedEvent:
    payload = doc(event_id, external_agent_id=EXTERNAL, **overrides)
    event = TelemetryEvent.model_validate(payload)
    if canonical is not None:
        event = TelemetryEvent.model_validate({**payload, "canonical_agent_id": canonical})
    return LoadedEvent(f"doc-{event_id}", event, status)


def model_call(event_id: str, status: str | None = "derived", **overrides: Any) -> LoadedEvent:
    return stamped(
        event_id,
        status,
        span_kind="model_call",
        provider="azure-openai",
        model="gpt-4o",
        model_version="2024-08",
        **overrides,
    )


def make_rig() -> Rig:
    return Rig([], [DOMAIN])


async def run(rig: Rig, *items: LoadedEvent) -> None:
    for item in items:
        rig.source.add(item)
        await rig.projection.handle(outbox_entry(item))


async def agents(rig: Rig) -> list[Agent]:
    scope = await rig.worker_scope()
    page = await rig.inner.list_entities(scope, EntityFilter(), PageRequest(page_size=200))
    return [e for e in page.items if isinstance(e, Agent)]


async def test_derived_event_creates_one_validating_draft_agent() -> None:
    rig = make_rig()
    await run(rig, stamped("e1"))
    found = await agents(rig)
    assert len(found) == 1
    agent = Agent.model_validate(found[0].model_dump(mode="json", by_alias=True))
    assert agent.id == DERIVED
    assert agent.lifecycle_status.root == "draft"
    assert agent.display_name.root == EXTERNAL
    assert agent.external_agent_id is not None and agent.external_agent_id.root == EXTERNAL
    assert agent.source_id.root == "sandbox-gateway"
    assert agent.domain_id.root == DOMAIN
    assert agent.attributes is not None
    assert agent.attributes.root["discovered_from"] == "telemetry"
    assert agent.attributes.root["agent_identity"] == "derived_from_external_id"
    assert rig.projection.stats.agent_drafts_created == 1


async def test_replay_creates_no_second_draft() -> None:
    rig = make_rig()
    item = stamped("e1")
    await run(rig, item)
    await run(rig, item, stamped("e2"))
    assert len(await agents(rig)) == 1
    assert rig.projection.stats.agent_drafts_created == 1
    assert rig.projection.stats.agent_drafts_existing == 2


async def test_existing_agent_is_never_updated() -> None:
    rig = make_rig()
    scope = await rig.worker_scope()
    seed = agent_discovery_entity(stamped("seed"), "2026-10-01T00:00:00Z")
    assert isinstance(seed, Agent)
    curated = seed.model_copy(
        update={
            "attributes": None,
            "display_name": seed.display_name.model_copy(update={"root": "Curated"}),
        }
    )
    created = await rig.inner.create_entity(scope, curated)
    await run(rig, stamped("e1"))
    after = await rig.inner.get_entity(scope, DERIVED)
    assert after == created
    assert rig.projection.stats.agent_drafts_created == 0
    assert rig.projection.stats.agent_drafts_existing == 1


@pytest.mark.parametrize("status", ["alias", "declared", "none", None])
async def test_other_resolutions_create_nothing(status: str | None) -> None:
    rig = make_rig()
    await run(rig, stamped("e1", status))
    assert await agents(rig) == []
    stats = rig.projection.stats
    assert stats.agent_drafts_created == 0
    assert stats.agent_undiscoverable_no_domain == 0
    assert stats.agent_draft_out_of_scope == 0


async def test_no_domain_is_counted() -> None:
    rig = make_rig()
    await run(rig, stamped("e1", domain_id=None))
    assert await agents(rig) == []
    assert rig.projection.stats.agent_undiscoverable_no_domain == 1


async def test_out_of_scope_domain_is_counted_not_quarantined() -> None:
    rig = make_rig()
    await run(rig, stamped("e1", domain_id=OTHER_DOMAIN))
    assert await agents(rig) == []
    assert rig.projection.stats.agent_draft_out_of_scope == 1
    assert rig.projection.stats.skipped_out_of_scope == 0
    assert rig.projection.quarantine.writes == 0  # type: ignore[attr-defined]


async def test_uses_model_edge_points_from_the_derived_agent() -> None:
    rig = make_rig()
    await run(rig, model_call("e1"))
    scope = await rig.worker_scope()
    assert rig.projection.stats.agent_drafts_created == 1
    assert rig.projection.stats.edges_written == 1
    edge_id = rig.repo.put_ids[0]
    edge = await rig.inner.get_edge(scope, edge_id)
    assert edge is not None
    assert edge.relation_type == "uses_model"
    assert edge.source_id == DERIVED
    entity = await rig.inner.get_entity(scope, DERIVED)
    assert isinstance(entity, Agent)
    assert entity.attributes is not None
    assert entity.attributes.root["agent_identity"] == "derived_from_external_id"
