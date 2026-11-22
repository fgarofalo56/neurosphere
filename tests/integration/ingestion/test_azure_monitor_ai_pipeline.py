"""PRP-141 item 5, emulator variant: Azure Monitor GenAI rows through the real edge and normalizer.

The recorded fixture rows are mapped by ``map_genai_row``, wrapped as the poller wraps them, and
pushed through the real ingest edge (producer source ``azure-monitor-ai``, kind ``application``).
The same window is pushed twice. The real ``IngestionConsumer`` (Event Hubs + Cosmos + Azurite
emulators) handles both, then the worker side reads the real archive and outbox:
``ResolvingTraceEventSource`` over ``ArchiveTraceEventSource`` feeds ``AggregateProjection`` and
``CatalogProjection``, as in PRP-137's integration file this one follows.

Run locally with ``docker compose up -d --wait`` (not run in the wave that added it: another lane
holds the compose stack). The in-process twin is ``tests/unit/azure_monitor_ai``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from neurosphere_connector_azure_monitor import GenAiRowSkipped, map_genai_row
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    AgentIdentitySettings,
    CatalogAgentDomainLookup,
    CatalogAliasLookup,
    declare_agent_alias,
    derive_agent_id,
)
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_workers.agent_identity import ResolvingTraceEventSource
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource

# The poller's own wrapper: reused so the proof covers exactly what the role posts.
from neurosphere_workers.ingestion.azure_monitor_ai.poller import (
    _cloud_event,  # type: ignore[reportPrivateUsage]
)
from neurosphere_workers.projections.catalog import CatalogProjection, WorkloadScopeProvider
from neurosphere_workers.projections.outbox import CosmosOutboxStore, OutboxEntry
from neurosphere_workers.runtime.archive_reader import ArchiveReader, ArchiveTraceEventSource

from .support import CountingConsumer, Pipeline, Producer, edge_client, push_cloudevents

_WORKER_TESTS = Path(__file__).resolve().parents[3] / "services" / "workers" / "tests"
if str(_WORKER_TESTS) not in sys.path:
    sys.path.append(str(_WORKER_TESTS))

from agent_identity_worker.pipeline_support import (  # type: ignore[import-not-found]  # noqa: E402
    DOMAIN,
    agent_doc,
    agent_id,
)
from projections.catalog_support import (  # type: ignore[import-not-found]  # noqa: E402
    WORKER_OBJECT_ID,
    Rig,
    StaticClaims,
    make_claims,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

CUSTOMER = "synthco"  # the in-memory catalog scope is for this customer; stores are per run
SOURCE = "azure-monitor-ai"
EXTERNAL = "support-bot"
DERIVED = derive_agent_id("commercial", CUSTOMER, SOURCE, EXTERNAL)
REAL = agent_id("support-bot")
MARKER = "CONTENT-MARKER"
FIXTURES = Path(__file__).resolve().parents[3] / "connectors/reference/azure-monitor/tests/fixtures"


@pytest.fixture(scope="module", autouse=True)
def _loopback_endpoints(_emulator_env: None) -> Iterator[None]:
    """127.0.0.1, never localhost: localhost -> ::1 breaks the Docker IPv6 forward."""
    patch = pytest.MonkeyPatch()
    patch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    try:
        yield
    finally:
        patch.undo()


def _rows(name: str) -> list[dict[str, Any]]:
    table = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


def mapped_events(
    *, customer_id: str = CUSTOMER, cloud: Any = "commercial"
) -> list[TelemetryEvent]:
    rows = _rows("genai_dependencies_response.json") + _rows("genai_requests_response.json")
    events: list[TelemetryEvent] = []
    for row in rows:
        try:
            events.append(
                map_genai_row(
                    row,
                    cloud=cloud,
                    customer_id=customer_id,
                    source_id=SOURCE,
                    domain_id=None,  # the resolver attributes one at read time
                )
            )
        except GenAiRowSkipped:
            continue
    return events


def wrapped(events: Sequence[TelemetryEvent]) -> list[dict[str, Any]]:
    return [_cloud_event(e) for e in events]


EVENTS = mapped_events()
COUNT = len(EVENTS)


@dataclass
class Landed:
    pipe: Pipeline
    consumer: CountingConsumer
    entries: list[OutboxEntry]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def landed(
    tmp_path_factory: pytest.TempPathFactory, fresh_hub: None
) -> AsyncIterator[Landed]:
    settings = Settings(env="local")
    producer = Producer("p-azmon", CUSTOMER, "commercial", {SOURCE: "application"})
    async with Pipeline.open(settings) as pipe:
        edge_dir = tmp_path_factory.mktemp("edge")
        async with edge_client(settings, [producer], edge_dir) as edge:
            first = await push_cloudevents(edge, producer, wrapped(EVENTS))
            second = await push_cloudevents(edge, producer, wrapped(EVENTS))  # the overlap re-read
        assert first.accepted == COUNT and second.accepted == COUNT
        assert not first.rejected_indexes and not second.rejected_indexes
        consumer = await pipe.consume(expect_processed=2 * COUNT)
        outbox = CosmosOutboxStore(
            pipe.database.get_container_client(pipe.ledger.outbox_container), settle_seconds=0
        )
        stored = await outbox.read_after(CUSTOMER, None, 100)
        entries = [s.entry for s in stored if s.entry.event_kind == "telemetry"]
        yield Landed(pipe, consumer, entries)


@dataclass
class Stack:
    rig: Rig
    resolver: AgentIdentityResolver
    store: InMemoryAggregateStore
    aggregates: AggregateProjection
    catalog: CatalogProjection

    def events(self, canonical: str) -> int:
        return sum(
            int(getattr(d, "event_count", 0))
            for d in self.store.documents(CUSTOMER).values()
            if d.series_key == f"agent:{canonical}" and d.grain == "hour"
        )


async def build_stack(landed: Landed, *, alias: bool) -> Stack:
    rig = Rig([], [DOMAIN])
    scope = await rig.worker_scope()
    await rig.inner.create_entity(scope, agent_doc("support-bot"))
    if alias:
        await declare_agent_alias(
            rig.inner,
            scope,
            source_id=SOURCE,
            external_agent_id=EXTERNAL,
            target_agent_id=REAL,
            clock=lambda: datetime.now(UTC),
        )
    settings = AgentIdentitySettings(discovery_domain=DOMAIN)
    resolver = AgentIdentityResolver(
        CatalogAliasLookup(rig.inner, lambda: scope),
        clock=lambda: 1000.0,
        domain_lookup=CatalogAgentDomainLookup(rig.inner, lambda: scope),
        discovery_domain_id=settings.discovery_domain,
    )
    reader = ArchiveReader(landed.pipe.archive_container)  # type: ignore[arg-type]
    source = ResolvingTraceEventSource(ArchiveTraceEventSource(reader), resolver)
    store = InMemoryAggregateStore()
    aggregates = AggregateProjection(
        store=store,
        ledger=StoreLedgerSource(InMemoryLedgerStore()),
        events=source,
        clock=lambda: datetime.now(UTC),
    )
    catalog = CatalogProjection(
        repository=rig.repo,  # type: ignore[arg-type]
        review_queue=rig.queue,
        source=source,
        scope_provider=WorkloadScopeProvider(
            rig.deriver, StaticClaims(make_claims(WORKER_OBJECT_ID))
        ),
    )
    return Stack(rig, resolver, store, aggregates, catalog)


async def drain(stack: Stack, landed: Landed) -> None:
    for entry in landed.entries:
        await stack.aggregates.handle(entry)
        await stack.catalog.handle(entry)


async def test_replayed_window_is_deduplicated_by_the_normalizer(landed: Landed) -> None:
    assert landed.consumer.accepted == COUNT
    assert landed.consumer.duplicates == COUNT
    assert not landed.consumer.quarantined
    assert len(landed.entries) == COUNT  # one outbox entry per event id, none for the replay
    ledger = await landed.pipe.cosmos_docs(landed.pipe.ledger.ledger_container, CUSTOMER)
    assert len(ledger) == COUNT


async def test_no_content_in_the_archive_or_the_stores(landed: Landed) -> None:
    records = await landed.pipe.archive_records(CUSTOMER)
    assert len(records) == COUNT
    assert MARKER not in json.dumps(records)
    for name, docs in (await landed.pipe.all_cosmos_docs()).items():
        assert MARKER not in json.dumps(docs), name
    assert not await landed.pipe.quarantine_records()


async def test_alias_present_series_under_the_aliased_agent(landed: Landed) -> None:
    stack = await build_stack(landed, alias=True)
    await drain(stack, landed)
    assert stack.events(REAL) >= 1
    assert stack.events(DERIVED) == 0
    assert stack.resolver.stats.resolved_alias >= 1


async def test_no_alias_series_under_derived_id_and_a_draft(landed: Landed) -> None:
    stack = await build_stack(landed, alias=False)
    await drain(stack, landed)
    assert stack.events(DERIVED) >= 1
    assert stack.events(REAL) == 0
    assert stack.catalog.stats.agent_drafts_created == 1
    assert stack.resolver.stats.derived >= 1


@pytest.mark.parametrize(
    ("customer", "cloud"),
    [("other-customer", "commercial"), (CUSTOMER, "government")],
    ids=["another-customer", "another-cloud"],
)
async def test_a_claim_for_another_customer_or_cloud_is_refused(
    tmp_path: Path, customer: str, cloud: str
) -> None:
    settings = Settings(env="local")
    producer = Producer("p-azmon-403", CUSTOMER, "commercial", {SOURCE: "application"})
    async with edge_client(settings, [producer], tmp_path) as edge:
        response = await edge.post(
            "/v1/ingest/events",
            headers={**producer.headers, "content-type": "application/cloudevents-batch+json"},
            content=json.dumps(wrapped(mapped_events(customer_id=customer, cloud=cloud))).encode(),
        )
    assert response.status_code == 403, response.text


async def test_a_raw_log_analytics_row_is_rejected_by_the_edge(tmp_path: Path) -> None:
    settings = Settings(env="local")
    producer = Producer("p-azmon-raw", CUSTOMER, "commercial", {SOURCE: "application"})
    raw_row = _rows("genai_dependencies_response.json")[0]
    async with edge_client(settings, [producer], tmp_path) as edge:
        response: httpx.Response = await edge.post(
            "/v1/ingest/events",
            headers={**producer.headers, "content-type": "application/cloudevents-batch+json"},
            content=json.dumps([raw_row]).encode(),
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] == 0
    assert [r["reason_code"] for r in body["rejected"]] == ["invalid_cloudevent"]
