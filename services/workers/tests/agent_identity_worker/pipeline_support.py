"""PRP-137 item 7: a rig that runs real OTLP JSON through the real normalisation pipeline.

OTLP span -> ``map_span`` -> hub message -> ``process_batch`` (ingestion fakes) -> archive fake ->
outbox entries -> ``AggregateProjection`` and ``CatalogProjection`` on ``ResolvingTraceEventSource``
over the archive, with in-memory aggregate and catalog stores and a ``CatalogAliasLookup``.

No event is built by hand with a canonical id: the only agent field a span can carry is
``gen_ai.agent.id``, which ``map_span`` writes to ``external_agent_id``. ``map_span`` leaves the
domain empty (the OTLP edge has no domain mapping today): the resolving source attributes one at
read time (the aliased agent's domain, or the discovery-domain setting), as in production.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingestion.support import Harness, hub_message, raw_from_bytes  # type: ignore[import-not-found]
from neurosphere_api.ingest.otlp_mapping import Scope, map_span
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    CatalogAgentDomainLookup,
    CatalogAliasLookup,
    declare_agent_alias,
)
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.catalog import EdgeFilter
from neurosphere_core.catalog.protocol import AliasKey
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.agent_identity import ResolvingTraceEventSource
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.ingestion.models import NormalizedEvent
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.projections.catalog import (
    CatalogProjection,
    TraceEventSource,
    WorkloadScopeProvider,
)
from neurosphere_workers.projections.outbox import OutboxEntry
from neurosphere_workers.runtime.archive_reader import ArchiveReader, ArchiveTraceEventSource
from projections.catalog_support import (  # type: ignore[import-not-found]
    WORKER_OBJECT_ID,
    Rig,
    StaticClaims,
    make_claims,
)

CLOUD = "commercial"
CUSTOMER = "synthco"
SOURCE = "otel-prod"
DOMAIN = f"{CLOUD}:{CUSTOMER}:sandbox:domain:dom-001"
DOMAIN_B = f"{CLOUD}:{CUSTOMER}:sandbox:domain:dom-002"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = "2026-11-01T11:30:00.000Z"
TRACE = "c1f91e05fc394d5f81060f328b0307b7"
START_NS = int(datetime(2026, 10, 31, 9, 0, 0, tzinfo=UTC).timestamp() * 1e9)
SCOPE = Scope(cloud=CLOUD, customer_id=CUSTOMER, source_id=SOURCE)

_AGENT_EXAMPLE = (
    Path(__file__).resolve().parents[4]
    / "packages/contracts/schemas/catalog/v1/examples/valid/agent.minimal-and-typical.json"
)


def attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def model_call_span(index: int, agent: str | None, *, trace: str = TRACE) -> dict[str, Any]:
    """One OTLP/JSON model_call span; ``agent`` None omits ``gen_ai.agent.id``."""
    attributes = [
        attr("gen_ai.operation.name", "chat"),
        attr("gen_ai.system", "azure_openai"),
        attr("gen_ai.request.model", "gpt-4o"),
        attr("gen_ai.usage.input_tokens", 100 + index),
        attr("gen_ai.usage.output_tokens", 20),
        attr("request_id", f"req-{trace[:6]}-{index}"),
    ]
    if agent is not None:
        attributes.append(attr("gen_ai.agent.id", agent))
    start = START_NS + index * 60_000_000_000
    return {
        "traceId": trace,
        "spanId": f"{index + 1:016x}",
        "parentSpanId": "",
        "name": "chat",
        "status": {"code": 1},
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(start + 250_000_000),
        "attributes": attributes,
    }


def otlp_document(spans: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "it"}, "spans": spans}],
            }
        ]
    }


def map_document(document: dict[str, Any]) -> list[TelemetryEvent]:
    """Exactly what ``ingest_otlp_traces`` does per span (no domain, no canonical id)."""
    return [
        map_span(span, SCOPE, RECEIVED_AT)
        for resource in document["resourceSpans"]
        for scope_spans in resource["scopeSpans"]
        for span in scope_spans["spans"]
    ]


class _Blob:
    def __init__(self, name: str) -> None:
        self.name = name


class _Download:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def readall(self) -> bytes:
        return self._raw


class ArchiveContainer:
    """Blob container fed from the ingestion archive fake (same layout the real sink writes)."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def add(self, normalized: NormalizedEvent) -> None:
        domain = normalized.contract.domain_id
        segment = domain.root.rsplit(":", 1)[-1] if domain is not None else "_none"
        day = normalized.event_time.strftime("%Y/%m/%d")
        name = f"{normalized.message.customer_id}/{segment}/{day}/{normalized.doc_id}.json.gz"
        payload = json.dumps(normalized.model_dump(mode="json")).encode("utf-8")
        self.blobs[name] = gzip.compress(payload)

    async def list_blobs(self, name_starts_with: str | None = None, **_: Any) -> AsyncIterator[Any]:
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield _Blob(name)

    async def download_blob(self, blob: str, **_: Any) -> _Download:
        return _Download(self.blobs[blob])


class SwitchLookup:
    """The catalog alias lookup with an outage switch and per-value overrides."""

    def __init__(self, inner: CatalogAliasLookup) -> None:
        self._inner = inner
        self.down = False
        self.overrides: dict[str, str] = {}
        self.calls = 0

    async def lookup(self, key: AliasKey) -> str | None:
        self.calls += 1
        if self.down:
            raise DependencyTransientError("catalog unavailable", reason="injected")
        if key.alias_value in self.overrides:
            return self.overrides[key.alias_value]
        return await self._inner.lookup(key)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def agent_doc(name: str, domain: str = DOMAIN) -> Agent:
    raw = json.loads(_AGENT_EXAMPLE.read_text(encoding="utf-8"))
    raw.update(
        id=f"{CLOUD}:{CUSTOMER}:foundry:agent:{name}",
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


def agent_id(name: str) -> str:
    return f"{CLOUD}:{CUSTOMER}:foundry:agent:{name}"


@dataclass
class World:
    harness: Harness
    container: ArchiveContainer
    reader: ArchiveReader
    rig: Rig
    scope: IdentityScope
    lookup: SwitchLookup
    clock: Clock
    resolver: AgentIdentityResolver
    store: InMemoryAggregateStore
    aggregates: AggregateProjection
    catalog: CatalogProjection
    outbox: list[OutboxEntry]

    async def declare(self, external: str, target_name: str) -> None:
        await declare_agent_alias(
            self.rig.inner,
            self.scope,
            source_id=SOURCE,
            external_agent_id=external,
            target_agent_id=agent_id(target_name),
            clock=lambda: NOW,
        )

    async def ingest(self, events: Sequence[TelemetryEvent]) -> None:
        """``process_batch`` over the events; fills the archive container and the outbox list."""
        raws = []
        for offset, event in enumerate(events):
            message = hub_message(event.model_dump(mode="json"), observation_kind="application")
            raws.append(raw_from_bytes(message.to_bytes(), offset))
        result = await process_batch(raws, self.harness.deps(), IngestionSettings())
        assert result.quarantined == {} or not any(result.quarantined.values())
        for doc_id, normalized in self.harness.archive.effects.items():
            if doc_id in {o.ref_id for o in self.outbox}:
                continue
            self.container.add(normalized)
            self.outbox.append(
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

    async def drain(self) -> None:
        """What the two outbox sinks do: handle every entry (raises on a transient failure)."""
        for entry in list(self.outbox):
            await self.aggregates.handle(entry)
            await self.catalog.handle(entry)

    def snapshot(self) -> dict[str, Any]:
        return {
            "docs": {
                k: v.model_dump(mode="json") for k, v in self.store.documents(CUSTOMER).items()
            },
            "contributions": {
                k: v.model_dump(mode="json") for k, v in self.store.contributions(CUSTOMER).items()
            },
        }

    def agent_events(self, canonical: str, *, grain: str = "hour") -> int:
        """Total ``model_call`` count in the ``agent:<id>`` subject series at ``grain``."""
        total = 0
        for stored in self.store.documents(CUSTOMER).values():
            if stored.series_key == f"agent:{canonical}".lower() and stored.grain == grain:
                total += int(getattr(stored, "event_count", 0))
        return total

    def doc_domains(self) -> set[str]:
        """Domains of every aggregate document that belongs to an ``agent:`` series."""
        return {
            d.domain_id
            for d in self.store.documents(CUSTOMER).values()
            if d.series_key.startswith("agent:")
        }

    def series_keys(self) -> set[str]:
        return {d.series_key for d in self.store.documents(CUSTOMER).values()}

    async def edges(self, flt: EdgeFilter | None = None, domain: str = DOMAIN) -> list[Any]:
        page = await self.rig.inner.list_edges_by_domain(
            self.scope, domain, flt or EdgeFilter(), PageRequest(page_size=200)
        )
        return list(page.items)

    async def agents(self) -> list[Agent]:
        from neurosphere_core.catalog import EntityFilter

        page = await self.rig.inner.list_entities(
            self.scope, EntityFilter(), PageRequest(page_size=200)
        )
        return [e for e in page.items if isinstance(e, Agent)]


async def make_world(
    *,
    aliases: Sequence[tuple[str, str]] = (),
    target_names: Sequence[str] = ("support-bot",),
    agent_domains: dict[str, str] | None = None,
    discovery_domain: str | None = None,
) -> World:
    """A fresh world; ``aliases`` are ``(external id, target agent name)`` declared up front."""
    harness = Harness()
    container = ArchiveContainer()
    reader = ArchiveReader(container)
    rig = Rig([], [DOMAIN, DOMAIN_B])
    scope = await rig.worker_scope()
    for name in target_names:
        await rig.inner.create_entity(
            scope, agent_doc(name, (agent_domains or {}).get(name, DOMAIN))
        )
    lookup = SwitchLookup(CatalogAliasLookup(rig.inner, lambda: scope))
    clock = Clock()
    resolver = AgentIdentityResolver(
        lookup,
        clock=clock,
        domain_lookup=CatalogAgentDomainLookup(rig.inner, lambda: scope),
        discovery_domain_id=discovery_domain,
    )
    inner: TraceEventSource = ArchiveTraceEventSource(reader)
    resolving = ResolvingTraceEventSource(inner, resolver)
    store = InMemoryAggregateStore()
    aggregates = AggregateProjection(
        store=store,
        ledger=StoreLedgerSource(InMemoryLedgerStore()),
        events=resolving,
        clock=lambda: NOW,
    )
    catalog = CatalogProjection(
        repository=rig.repo,  # type: ignore[arg-type]
        review_queue=rig.queue,
        source=resolving,
        scope_provider=WorkloadScopeProvider(
            rig.deriver, StaticClaims(make_claims(WORKER_OBJECT_ID))
        ),
        clock=lambda: NOW,
    )
    world = World(
        harness,
        container,
        reader,
        rig,
        scope,
        lookup,
        clock,
        resolver,
        store,
        aggregates,
        catalog,
        [],
    )
    for external, target in aliases:
        await world.declare(external, target)
    return world
