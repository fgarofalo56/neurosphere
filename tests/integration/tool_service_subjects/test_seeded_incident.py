"""PRP-100 item 5: the PRP-71 seeded incident, aggregated in memory, fails a service and a tool.

Offline and deterministic: no compose, no network, no ``integration`` marker. The seeded
``TelemetryEvent`` documents go through the real ``AggregateProjection`` handler over in-memory
stores; every id asserted comes from ``incident-manifest.json`` or from the seeded events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.aggregates import (
    AggregateWindow,
    InMemoryAggregateStore,
    SubjectPoint,
    health_for_error_rate,
    subject_series_key,
)
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.projections.catalog import InMemoryTraceEventSource, LoadedEvent
from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxReader,
)

from sandbox.demo.build import build_demo_world
from sandbox.demo.incident import build_demo_telemetry, incident_manifest, write_incident_manifest

Doc = dict[str, Any]
SEED = 1
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FAILING_TOOL_RATE = 0.25


def _parse(text: str) -> datetime:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)


class Seeded:
    """The drained aggregates plus what the seeded events say about ids."""

    def __init__(self, manifest: Doc, events: list[Doc], store: InMemoryAggregateStore) -> None:
        self.manifest = manifest
        self.events = events
        self.store = store
        self.customer = events[0]["customer_id"]
        start, end = manifest["window"]["start"], manifest["window"]["end"]
        self.window = AggregateWindow(_parse(start), _parse(end))

    async def points(self, domain: str, kind: Any, ids: set[str]) -> dict[str, SubjectPoint]:
        keys = [subject_series_key(kind, i) for i in sorted(ids)]
        lookup = await self.store.latest_subject_points(
            self.customer, domain, kind, keys, self.window
        )
        return lookup.points


@pytest.fixture(scope="module")
async def seeded(tmp_path_factory: pytest.TempPathFactory) -> Seeded:
    world = build_demo_world("commercial")
    tele = build_demo_telemetry(world, SEED)
    assert incident_manifest(world, SEED) == tele.manifest
    path = tmp_path_factory.mktemp("incident") / "incident-manifest.json"
    write_incident_manifest(tele.manifest, path)
    manifest: Doc = json.loads(path.read_text(encoding="utf-8"))

    customer = tele.events[0]["customer_id"]
    store = InMemoryAggregateStore()
    source = InMemoryTraceEventSource()
    outbox = InMemoryOutboxStore()
    end = _parse(manifest["window"]["end"])
    projection = AggregateProjection(
        store=store,
        ledger=StoreLedgerSource(InMemoryLedgerStore()),
        events=source,
        prices=_no_prices(),
        clock=lambda: end,
    )
    for n, doc in enumerate(tele.events):
        loaded = LoadedEvent(doc_id=f"ev-{n:06d}", event=TelemetryEvent.model_validate(doc))
        source.add(loaded)
        await outbox.append(
            OutboxEntry(
                id=loaded.doc_id,
                customer_id=customer,
                kind="event",
                ref_id=loaded.doc_id,
                entity="event",
                event_kind="telemetry",
            )
        )
    reader = OutboxReader(outbox, InMemoryCheckpointStore(), batch_size=500)
    result = await reader.drain(SINK_AGGREGATES, customer, projection)
    assert result.ok
    return Seeded(manifest, tele.events, store)


def _no_prices() -> Any:
    from neurosphere_core.ledger import PriceTable

    return PriceTable([])


def _domains_of(events: list[Doc], field: str, ident: str, kind_key: str) -> set[str]:
    return {e["domain_id"] for e in events if e.get(field, {}).get(kind_key) == ident}


async def test_outage_service_is_failing_and_another_service_ok(seeded: Seeded) -> None:
    sid = seeded.manifest["service_id"]
    floor = seeded.manifest["effects"]["health_failing_error_rate"]
    domains = _domains_of(seeded.events, "service", sid, "canonical_service_id")
    assert domains
    outage: list[SubjectPoint] = []
    for domain in domains:
        got = await seeded.points(domain, "service", {sid})
        outage += list(got.values())
    assert outage
    rates = [p.error_rate for p in outage if p.error_rate is not None]
    assert rates and max(rates) >= floor
    assert health_for_error_rate(max(rates)) == "failing"

    others = {
        e["service"]["canonical_service_id"]
        for e in seeded.events
        if "service" in e and e["service"]["canonical_service_id"] != sid
    }
    assert others
    ok: list[float] = []
    for domain in {e["domain_id"] for e in seeded.events}:
        for p in (await seeded.points(domain, "service", others)).values():
            if p.error_rate is not None and health_for_error_rate(p.error_rate) == "ok":
                ok.append(p.error_rate)
    assert ok


async def test_a_tool_calling_the_outage_service_fails(seeded: Seeded) -> None:
    sid = seeded.manifest["service_id"]
    tool_ids = {
        e["tool"]["canonical_tool_id"]
        for e in seeded.events
        if e["span_kind"] == "tool_call"
        and e.get("service", {}).get("canonical_service_id") == sid
        and "tool" in e
    }
    assert tool_ids
    found: dict[str, float] = {}
    for domain in {e["domain_id"] for e in seeded.events}:
        for key, p in (await seeded.points(domain, "tool", tool_ids)).items():
            if p.error_rate is not None:
                found[key] = max(found.get(key, 0.0), p.error_rate)
    assert any(rate >= FAILING_TOOL_RATE for rate in found.values()), found


async def test_agent_points_still_come_from_model_calls(seeded: Seeded) -> None:
    down = set(seeded.manifest["downstream_agent_ids"])
    assert down
    seen: set[str] = set()
    for domain in {e["domain_id"] for e in seeded.events}:
        for key in await seeded.points(domain, "agent", down):
            seen.add(key.removeprefix("agent:"))
    assert seen == down


async def test_tool_and_service_points_carry_no_tokens(seeded: Seeded) -> None:
    checked = 0
    for domain in {e["domain_id"] for e in seeded.events}:
        for kind, field, key in (
            ("tool", "tool", "canonical_tool_id"),
            ("service", "service", "canonical_service_id"),
        ):
            ids = {e[field][key] for e in seeded.events if field in e}
            for p in (await seeded.points(domain, kind, ids)).values():
                checked += 1
                assert p.input_tokens is None and p.output_tokens is None
    assert checked
