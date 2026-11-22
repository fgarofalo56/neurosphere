"""PRP-141 item 5: Azure Monitor GenAI rows travel the same front door and pipeline as every source.

fixture rows -> ``map_genai_row`` -> wrapped exactly as the poller wraps them -> the real
``IngestService.ingest_events`` (producer with an ``application`` source ``azure-monitor-ai``) ->
``process_batch`` with the ingestion fakes -> archive fake -> outbox -> ``AggregateProjection`` and
``CatalogProjection`` on PRP-137's ``ResolvingTraceEventSource``. No event carries a canonical
agent id: the resolver (aliases, derived id, drafts) is the only place identity is decided.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.ingest.auth import (
    ProducerRegistration,
    RegisteredCredentialAuthenticator,
    StaticProducerRegistry,
    hash_secret,
)
from neurosphere_api.ingest.cloudevents import BATCH_MEDIA_TYPE
from neurosphere_api.ingest.limits import TokenBucketLimiter
from neurosphere_api.ingest.publisher import InMemoryPublisher
from neurosphere_api.ingest.reasons import ReasonCode
from neurosphere_api.ingest.service import IngestResult, IngestService
from neurosphere_api.ingest.settings import IngestSettings
from neurosphere_connector_azure_monitor import GenAiRowSkipped, map_genai_row
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import declare_agent_alias, derive_agent_id
from neurosphere_core.errors import ForbiddenError
from neurosphere_workers.ingestion.models import NormalizedEvent
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.projections.outbox import OutboxEntry

# PRP-137's rig lives with the worker tests; its integration file imports it the same way.
_WORKER_TESTS = Path(__file__).resolve().parents[3] / "services" / "workers" / "tests"
if str(_WORKER_TESTS) not in sys.path:
    sys.path.append(str(_WORKER_TESTS))

from agent_identity_worker.pipeline_support import (  # type: ignore[import-not-found]  # noqa: E402
    CLOUD,
    CUSTOMER,
    DOMAIN,
    NOW,
    World,
    agent_id,
    make_world,
)
from ingestion.support import raw_from_bytes  # type: ignore[import-not-found]  # noqa: E402

# The poller's own wrapper: reused, never re-implemented, so the proof covers what it posts.
from neurosphere_workers.ingestion.azure_monitor_ai.poller import (  # noqa: E402
    _cloud_event,  # type: ignore[reportPrivateUsage]
)

SOURCE = "azure-monitor-ai"  # the poller's default source id
EXTERNAL = "support-bot"
DERIVED = derive_agent_id(CLOUD, CUSTOMER, SOURCE, EXTERNAL)
REAL = agent_id("support-bot")
MARKER = "CONTENT-MARKER"
FIXTURES = Path(__file__).resolve().parents[3] / "connectors/reference/azure-monitor/tests/fixtures"
SECRET = "unit-test-secret"
SINKS = 2  # aggregates and catalog each resolve every event through the shared resolver


def _rows(name: str) -> list[dict[str, Any]]:
    table = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


ROWS = _rows("genai_dependencies_response.json") + _rows("genai_requests_response.json")
CONTENT_ROW_ID = "7777777777777777"  # the fixture row that carries the CONTENT-MARKER values


def map_rows(
    rows: Sequence[dict[str, Any]],
    *,
    customer_id: str = CUSTOMER,
    cloud: Any = CLOUD,
    domain_id: str | None = None,
) -> list[TelemetryEvent]:
    events: list[TelemetryEvent] = []
    for row in rows:
        try:
            events.append(
                map_genai_row(
                    row,
                    cloud=cloud,
                    customer_id=customer_id,
                    source_id=SOURCE,
                    domain_id=domain_id,
                )
            )
        except GenAiRowSkipped:
            continue
    return events


def registration(
    *, customer: str = CUSTOMER, cloud: str = CLOUD, kind: str = "application"
) -> ProducerRegistration:
    return ProducerRegistration.model_validate(
        {
            "producer_id": "p-azmon",
            "secret_sha256": hash_secret(SECRET),
            "customer_id": customer,
            "cloud": cloud,
            "sources": {SOURCE: kind},
        }
    )


class Edge:
    """The real ``IngestService`` with an in-memory publisher (what the HTTP route calls)."""

    def __init__(self, producer: ProducerRegistration | None = None, edge_cloud: str = CLOUD):
        self.producer = producer or registration()
        self.publisher = InMemoryPublisher()
        self.service = IngestService(
            settings=IngestSettings(),
            edge_cloud=edge_cloud,
            authenticator=RegisteredCredentialAuthenticator(
                StaticProducerRegistry([self.producer])
            ),
            publisher=self.publisher,
            limiter=TokenBucketLimiter(rate_per_second=1000.0, burst=1000),
            now=lambda: NOW,
        )

    async def post_raw(self, body: Any) -> IngestResult:
        producer = self.service.authorize(f"Bearer {self.producer.producer_id}.{SECRET}")
        return await self.service.ingest_events(
            producer, json.dumps(body).encode("utf-8"), BATCH_MEDIA_TYPE
        )

    async def post(self, events: Sequence[TelemetryEvent]) -> IngestResult:
        """Exactly the poller's wrapping, as one CloudEvents batch."""
        return await self.post_raw([_cloud_event(e) for e in events])


async def feed(world: World, edge: Edge, start: int = 0) -> Any:
    """Hub messages the edge published -> ``process_batch`` -> archive container and outbox."""
    raws = [
        raw_from_bytes(message.to_bytes(), start + i)
        for i, message in enumerate(edge.publisher.messages[start:])
    ]
    result = await process_batch(raws, world.harness.deps(), IngestionSettings())
    assert not any(result.quarantined.values()), result.quarantined
    known = {o.ref_id for o in world.outbox}
    for doc_id, normalized in world.harness.archive.effects.items():
        if doc_id in known:
            continue
        _add_to_world(world, doc_id, normalized)
    return result


def _add_to_world(world: World, doc_id: str, normalized: NormalizedEvent) -> None:
    world.container.add(normalized)
    world.outbox.append(
        OutboxEntry(
            id=doc_id,
            customer_id=normalized.message.customer_id,
            kind="event",
            ref_id=doc_id,
            entity="event",
            source_id=normalized.message.source_id,
            event_kind="telemetry",
            occurred_at=normalized.event_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        )
    )


async def declare(world: World) -> None:
    await declare_agent_alias(
        world.rig.inner,
        world.scope,
        source_id=SOURCE,
        external_agent_id=EXTERNAL,
        target_agent_id=REAL,
        clock=lambda: NOW,
    )


def test_fixture_rows_are_usable_and_include_the_content_row() -> None:
    events = map_rows(ROWS)
    assert 4 <= len(events) < len(ROWS)  # the non-hex id row is skipped, never guessed
    assert any(e.event_id.root.endswith(f":{CONTENT_ROW_ID}") for e in events)
    assert all(e.canonical_agent_id is None for e in events)  # identity is the resolver's job
    assert any(str(row.get("gen_ai.input.messages") or "").startswith(MARKER) for row in ROWS)


async def test_alias_present_counts_for_the_aliased_agent() -> None:
    world = await make_world()
    await declare(world)
    edge = Edge()
    events = map_rows(ROWS)
    result = await edge.post(events)
    assert result.accepted == len(events) and not result.rejected
    outcome = await feed(world, edge)
    assert outcome.accepted == len(events)
    await world.drain()

    assert world.agent_events(REAL) >= 1  # the aliased canonical agent's model calls
    assert world.agent_events(DERIVED) == 0
    assert world.resolver.stats.resolved_alias >= SINKS
    assert world.catalog.stats.agent_drafts_created == 0
    assert world.doc_domains() == {DOMAIN}  # no domain on the event: the agent's own is used


async def test_no_alias_uses_the_derived_id_and_creates_a_draft() -> None:
    world = await make_world(discovery_domain=DOMAIN)
    edge = Edge()
    events = map_rows(ROWS)
    await edge.post(events)
    await feed(world, edge)
    await world.drain()

    assert world.agent_events(DERIVED) >= 1
    assert world.agent_events(REAL) == 0
    assert not world.harness.quarantine.effects  # nothing dropped
    drafts = [a for a in await world.agents() if a.id == DERIVED]
    assert len(drafts) == 1
    assert drafts[0].external_agent_id is not None
    assert drafts[0].external_agent_id.root == EXTERNAL
    assert world.catalog.stats.agent_drafts_created == 1
    assert world.resolver.stats.derived >= SINKS


async def test_the_same_window_twice_adds_nothing() -> None:
    world = await make_world()
    await declare(world)
    edge = Edge()
    events = map_rows(ROWS)

    await edge.post(events)
    first = await feed(world, edge)
    await world.drain()
    snapshot = world.snapshot()
    archived = dict(world.harness.archive.effects)
    ledger = dict(world.harness.ledger.effects)
    outbox = list(world.outbox)
    assert first.accepted == len(events) and first.duplicates == 0

    # the poller's overlap re-reads the window: the edge accepts, the normalizer dedupes
    again = await edge.post(events)
    assert again.accepted == len(events)  # the edge has no state; dedupe is the normalizer's job
    second = await feed(world, edge, start=len(events))
    await world.drain()

    assert second.accepted == 0
    assert second.duplicates == len(events)
    assert world.harness.archive.effects == archived
    assert world.harness.ledger.effects == ledger
    assert world.outbox == outbox
    assert world.snapshot() == snapshot  # no second aggregate contribution
    assert len(ledger) == len(events)


async def test_content_never_reaches_the_archive_record() -> None:
    world = await make_world()
    edge = Edge()
    content_rows = [r for r in ROWS if r["Id"] == CONTENT_ROW_ID]
    assert len(content_rows) == 1
    events = map_rows(content_rows)
    assert len(events) == 1
    result = await edge.post(events)
    assert result.accepted == 1
    await feed(world, edge)
    await world.drain()

    assert len(world.container.blobs) == 1
    for blob in world.container.blobs.values():
        assert MARKER not in gzip.decompress(blob).decode("utf-8")
    assert MARKER not in json.dumps([m.model_dump(mode="json") for m in edge.publisher.messages])
    assert all(MARKER not in n.model_dump_json() for n in world.harness.archive.effects.values())
    assert all(MARKER not in n.model_dump_json() for n in world.harness.ledger.effects.values())
    assert MARKER not in json.dumps(world.snapshot())
    # the same row is the model_call the aggregate counts (the proof is not vacuous)
    assert world.store.documents(CUSTOMER)  # the row was aggregated, so the scan above saw it
    assert len(world.harness.ledger.effects) == 1


@pytest.mark.parametrize(
    ("customer", "cloud"),
    [("other-customer", CLOUD), (CUSTOMER, "government")],
    ids=["another-customer", "another-cloud"],
)
async def test_a_claim_for_another_customer_or_cloud_is_refused(customer: str, cloud: str) -> None:
    edge = Edge()
    events = map_rows(ROWS, customer_id=customer, cloud=cloud)
    assert events
    with pytest.raises(ForbiddenError) as raised:
        await edge.post(events)
    assert raised.value.reason == ReasonCode.CLAIM_MISMATCH
    assert edge.publisher.messages == []  # nothing published


async def test_a_producer_on_another_cloud_is_refused_at_the_edge() -> None:
    edge = Edge(producer=registration(cloud="government"), edge_cloud=CLOUD)
    with pytest.raises(ForbiddenError) as raised:
        await edge.post(map_rows(ROWS))
    assert raised.value.reason == ReasonCode.CLOUD_MISMATCH
    assert edge.publisher.messages == []


async def test_a_raw_log_analytics_row_cannot_bypass_the_edge_schema() -> None:
    edge = Edge()
    raw_row = next(r for r in ROWS if r["Id"] == "1111111111111111")

    bare = await edge.post_raw([raw_row])  # a row posted as is, not a CloudEvent
    assert bare.accepted == 0
    assert [r.reason_code for r in bare.rejected] == [ReasonCode.INVALID_CLOUDEVENT]

    wrapped = {  # a row wrapped as a telemetry CloudEvent but never mapped
        "specversion": "1.0",
        "id": "raw-1",
        "source": "neurosphere/azure-monitor-ai",
        "type": _cloud_event(map_rows([raw_row])[0])["type"],
        "data": raw_row,
    }
    unmapped = await edge.post_raw([wrapped])
    assert unmapped.accepted == 0
    assert [r.reason_code for r in unmapped.rejected] == [ReasonCode.INVALID_EVENT]
    assert edge.publisher.messages == []


async def test_the_producer_source_kind_is_what_the_pipeline_records() -> None:
    """The registration (``application``), not the payload, decides the observation kind."""
    edge = Edge()
    events = map_rows(ROWS)
    await edge.post(events)
    assert {m.observation_kind for m in edge.publisher.messages} == {"application"}
    assert {m.source_id for m in edge.publisher.messages} == {SOURCE}
