"""PRP-137 item 7, emulator variant: OTLP agent spans through the real edge and normalizer.

``gen_ai.agent.id`` spans are pushed through the real OTLP edge, consumed by the real
``IngestionConsumer`` (Event Hubs + Cosmos + Azurite emulators), then the worker side reads the
real archive and the real outbox: ``ResolvingTraceEventSource`` over ``ArchiveTraceEventSource``
feeds ``AggregateProjection`` and ``CatalogProjection`` (in-memory aggregate and catalog stores,
``CatalogAliasLookup`` over an in-memory catalog repository).

Run locally with ``docker compose up -d --wait``; the emulator endpoints below use 127.0.0.1.
The OTLP edge sets no ``domain_id`` today, so the catalog side is asserted through its draft and
undiscoverable counters rather than an edge.
"""

from __future__ import annotations

import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    CatalogAliasLookup,
    declare_agent_alias,
    derive_agent_id,
)
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_workers.agent_identity import ResolvingTraceEventSource, reresolve_external_id
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.projections.catalog import CatalogProjection, WorkloadScopeProvider
from neurosphere_workers.projections.outbox import CosmosOutboxStore, OutboxEntry
from neurosphere_workers.runtime.archive_reader import ArchiveReader, ArchiveTraceEventSource

from .support import Pipeline, Producer, edge_client, otlp_attr, push_otlp_traces

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

CUSTOMER = "synthco"  # the in-memory catalog scope is for this customer; every store here is
# per run (unique Cosmos database and blob containers), so runs cannot see each other
SOURCE = "otel-prod"
EXTERNAL = "support-bot"
DERIVED = derive_agent_id("commercial", CUSTOMER, SOURCE, EXTERNAL)
REAL = agent_id("support-bot")
SPANS = 3


@pytest.fixture(scope="module", autouse=True)
def _loopback_endpoints(_emulator_env: None) -> Iterator[None]:
    """127.0.0.1, never localhost: localhost -> ::1 breaks the Docker IPv6 forward."""
    patch = pytest.MonkeyPatch()
    patch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    try:
        yield
    finally:
        patch.undo()


def _spans() -> dict[str, Any]:
    trace = uuid.uuid4().hex
    base_ns = int(time.time() * 1e9) - 600_000_000_000
    spans = []
    for i in range(SPANS):
        start = base_ns + i * 1_000_000_000
        spans.append(
            {
                "traceId": trace,
                "spanId": f"{i + 1:016x}",
                "parentSpanId": "",
                "name": "chat",
                "status": {"code": 1},
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + 250_000_000),
                "attributes": [
                    otlp_attr("gen_ai.operation.name", "chat"),
                    otlp_attr("gen_ai.system", "azure_openai"),
                    otlp_attr("gen_ai.request.model", "synthetic-model"),
                    otlp_attr("gen_ai.usage.input_tokens", 100 + i),
                    otlp_attr("gen_ai.usage.output_tokens", 20),
                    otlp_attr("request_id", f"agent-id-{trace[:6]}-{i}"),
                    otlp_attr("gen_ai.agent.id", EXTERNAL),
                ],
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "it"}, "spans": spans}],
            }
        ]
    }


@dataclass
class Landed:
    pipe: Pipeline
    entries: list[OutboxEntry]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def landed(
    tmp_path_factory: pytest.TempPathFactory, fresh_hub: None
) -> AsyncIterator[Landed]:
    settings = Settings(env="local")
    producer = Producer("p-otlp", CUSTOMER, "commercial", {SOURCE: "application"})
    async with Pipeline.open(settings) as pipe:
        edge_dir = tmp_path_factory.mktemp("edge")
        async with edge_client(settings, [producer], edge_dir) as edge:
            body = await push_otlp_traces(edge, producer, _spans())
        assert body["accepted"] == SPANS
        await pipe.consume(expect_processed=SPANS)
        outbox = CosmosOutboxStore(
            pipe.database.get_container_client(pipe.ledger.outbox_container), settle_seconds=0
        )
        stored = await outbox.read_after(CUSTOMER, None, 100)
        entries = [s.entry for s in stored if s.entry.event_kind == "telemetry"]
        assert len(entries) == SPANS
        yield Landed(pipe, entries)


@dataclass
class Stack:
    rig: Rig
    lookup_clock: list[float]
    resolver: AgentIdentityResolver
    reader: ArchiveReader
    store: InMemoryAggregateStore
    aggregates: AggregateProjection
    catalog: CatalogProjection

    def events(self, canonical: str) -> int:
        return sum(
            int(getattr(d, "event_count", 0))
            for d in self.store.documents(CUSTOMER).values()
            if d.series_key == f"agent:{canonical}" and d.grain == "hour"
        )

    def agent_series(self) -> set[str]:
        return {d.series_key for d in self.store.documents(CUSTOMER).values()}


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
    ticks = [1000.0]
    resolver = AgentIdentityResolver(
        CatalogAliasLookup(rig.inner, lambda: scope), clock=lambda: ticks[0]
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
    return Stack(rig, ticks, resolver, reader, store, aggregates, catalog)


async def drain(stack: Stack, landed: Landed) -> None:
    for entry in landed.entries:
        await stack.aggregates.handle(entry)
        await stack.catalog.handle(entry)


async def test_alias_present_series_under_the_aliased_agent(landed: Landed) -> None:
    stack = await build_stack(landed, alias=True)
    await drain(stack, landed)
    assert stack.events(REAL) == SPANS
    assert stack.events(DERIVED) == 0
    assert stack.resolver.stats.resolved_alias >= SPANS


async def test_no_alias_series_under_derived_id_and_nothing_dropped(landed: Landed) -> None:
    stack = await build_stack(landed, alias=False)
    await drain(stack, landed)
    assert stack.events(DERIVED) == SPANS
    assert stack.resolver.stats.derived >= SPANS
    assert not await landed.pipe.quarantine_records()
    # the OTLP edge sets no domain, so a draft can only be created once one is mapped
    stats = stack.catalog.stats
    assert stats.agent_drafts_created + stats.agent_undiscoverable_no_domain == SPANS


async def test_alias_added_later_reresolve_moves_the_series(landed: Landed) -> None:
    stack = await build_stack(landed, alias=False)
    await drain(stack, landed)
    assert stack.events(DERIVED) == SPANS

    scope = await stack.rig.worker_scope()
    await declare_agent_alias(
        stack.rig.inner,
        scope,
        source_id=SOURCE,
        external_agent_id=EXTERNAL,
        target_agent_id=REAL,
        clock=lambda: datetime.now(UTC),
    )
    stack.lookup_clock[0] += 1000  # past the negative cache TTL
    args: dict[str, Any] = {
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "external_agent_id": EXTERNAL,
        "reader": stack.reader,
        "aggregates": stack.aggregates,
        "store": stack.store,
        "catalog": stack.catalog,
        "max_events": 100,
        "resolver_stats": stack.resolver.stats,
    }
    report = await reresolve_external_id(**args)
    assert report.moved == SPANS
    assert stack.events(REAL) == SPANS
    assert stack.events(DERIVED) == 0
    assert f"agent:{DERIVED}" not in stack.agent_series()

    before = {k: v.model_dump(mode="json") for k, v in stack.store.documents(CUSTOMER).items()}
    again = await reresolve_external_id(**args)
    assert again.moved == 0
    assert before == {
        k: v.model_dump(mode="json") for k, v in stack.store.documents(CUSTOMER).items()
    }
