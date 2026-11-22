"""PRP-137 item 4: the re-resolution job moves contributions to a later-declared alias."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import AgentIdentityResolver, derive_agent_id
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.ledger import InMemoryLedgerStore
from neurosphere_workers.agent_identity import (
    ReresolveError,
    ResolvingTraceEventSource,
    reresolve_external_id,
)
from neurosphere_workers.agent_identity.__main__ import (
    EXIT_NOT_WIRED,
    EXIT_OK,
    EXIT_TRUNCATED,
    EXIT_USAGE,
    DependenciesNotWiredError,
    ReresolveDependencies,
    build_arg_parser,
    main,
)
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.projections.catalog import CatalogProjection, WorkloadScopeProvider
from neurosphere_workers.projections.outbox import OutboxEntry
from neurosphere_workers.runtime.archive_reader import ArchiveReader, ArchiveTraceEventSource
from projections.catalog_support import (  # type: ignore[import-not-found]
    WORKER_OBJECT_ID,
    Rig,
    StaticClaims,
    make_claims,
)

from .fakes import CUSTOMER, StubLookup, doc

DOMAIN = f"commercial:{CUSTOMER}:sandbox:domain:dom-001"
SOURCE = "sandbox-gateway"
EXTERNAL = "My Agent 1"
DERIVED = derive_agent_id("commercial", CUSTOMER, SOURCE, EXTERNAL)
ALIASED = f"commercial:{CUSTOMER}:sandbox:agent:real-agent"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


class _Blob:
    def __init__(self, name: str) -> None:
        self.name = name


class _Download:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def readall(self) -> bytes:
        return self._raw


class FakeContainer:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def add(self, name: str, record: dict[str, Any]) -> None:
        self.blobs[name] = gzip.compress(json.dumps(record).encode("utf-8"))

    async def list_blobs(self, name_starts_with: str | None = None, **_: Any) -> AsyncIterator[Any]:
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield _Blob(name)

    async def download_blob(self, blob: str, **_: Any) -> _Download:
        return _Download(self.blobs[blob])


def model_call(event_id: str, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "external_agent_id": EXTERNAL,
        "span_kind": "model_call",
        "provider": "azure-openai",
        "model": "gpt-4o",
        "model_version": "2024-08",
    }
    fields.update(overrides)
    return doc(event_id, **fields)


def add_event(
    container: FakeContainer, payload: dict[str, Any], *, message_customer: str = CUSTOMER
) -> str:
    customer = str(payload["customer_id"])
    doc_id = compute_doc_id(customer, str(payload["source_id"]), str(payload["event_id"]))
    day = str(payload["event_time"])[:10].replace("-", "/")
    record = {
        "doc_id": doc_id,
        "message": {"kind": "telemetry", "customer_id": message_customer},
        "contract": payload,
    }
    container.add(f"{CUSTOMER}/dom-001/{day}/{doc_id}.json.gz", record)
    return doc_id


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class World:
    container: FakeContainer
    lookup: StubLookup
    clock: Clock
    resolver: AgentIdentityResolver
    reader: ArchiveReader
    store: InMemoryAggregateStore
    aggregates: AggregateProjection
    catalog: CatalogProjection
    rig: Rig

    async def apply_all(self) -> None:
        """What the outbox dispatch would do: handle every archived telemetry event once."""
        for doc_id, name in sorted((await self.reader.names(CUSTOMER)).items()):
            record = await self.reader.read(CUSTOMER, name)
            assert record is not None
            event = TelemetryEvent.model_validate(record["contract"])
            if event.customer_id.root != CUSTOMER:
                continue
            out = OutboxEntry(
                id=doc_id,
                customer_id=CUSTOMER,
                kind="event",
                ref_id=doc_id,
                entity="event",
                event_kind="telemetry",
            )
            await self.aggregates.handle(out)
            await self.catalog.handle(out)

    def snapshot(self) -> dict[str, Any]:
        return {
            "docs": {
                k: v.model_dump(mode="json") for k, v in self.store.documents(CUSTOMER).items()
            },
            "contributions": {
                k: v.model_dump(mode="json") for k, v in self.store.contributions(CUSTOMER).items()
            },
        }


def make_world(container: FakeContainer, aliases: dict[str, str] | None = None) -> World:
    lookup = StubLookup(aliases)
    clock = Clock()
    resolver = AgentIdentityResolver(lookup, clock=clock)
    reader = ArchiveReader(container)
    resolving = ResolvingTraceEventSource(ArchiveTraceEventSource(reader), resolver)
    store = InMemoryAggregateStore()
    aggregates = AggregateProjection(
        store=store,
        ledger=StoreLedgerSource(InMemoryLedgerStore()),
        events=resolving,
        clock=lambda: NOW,
    )
    rig = Rig([], [DOMAIN])
    catalog = CatalogProjection(
        repository=rig.repo,  # type: ignore[arg-type]
        review_queue=rig.queue,
        source=resolving,
        scope_provider=WorkloadScopeProvider(
            rig.deriver, StaticClaims(make_claims(WORKER_OBJECT_ID))
        ),
        clock=lambda: NOW,
    )
    return World(container, lookup, clock, resolver, reader, store, aggregates, catalog, rig)


def three_events() -> FakeContainer:
    container = FakeContainer()
    for n in (1, 2, 3):
        add_event(
            container,
            model_call(
                f"e{n}", event_time=f"2026-10-0{n}T01:07:21.470Z", span_id=f"f6c75e5fa45fb23{n}"
            ),
        )
    return container


async def run_job(world: World, **overrides: Any) -> Any:
    args: dict[str, Any] = {
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
    args.update(overrides)
    return await reresolve_external_id(**args)


def series_agents(world: World) -> set[str]:
    return {
        agent
        for agent in (DERIVED, ALIASED)
        if any(agent in d.series_key for d in world.store.documents(CUSTOMER).values())
    }


async def test_alias_added_later_moves_contributions_and_matches_from_scratch() -> None:
    world = make_world(three_events())
    await world.apply_all()
    assert series_agents(world) == {DERIVED}

    world.lookup.values[EXTERNAL] = ALIASED
    world.clock.now += 1000  # past the negative cache TTL
    report = await run_job(world)

    assert (report.examined, report.matched, report.reapplied, report.moved) == (3, 3, 3, 3)
    assert report.truncated is False
    assert world.resolver.stats.contributions_moved == 3
    assert series_agents(world) == {ALIASED}  # old derived series points are gone

    fresh = make_world(three_events(), {EXTERNAL: ALIASED})
    await fresh.apply_all()
    assert world.snapshot() == fresh.snapshot()


async def test_second_run_changes_nothing() -> None:
    world = make_world(three_events())
    await world.apply_all()
    world.lookup.values[EXTERNAL] = ALIASED
    world.clock.now += 1000
    await run_job(world)
    before = world.snapshot()

    second = await run_job(world)

    assert second.moved == 0
    assert second.reapplied == 3
    assert world.snapshot() == before


async def test_truncated_scan_is_reported() -> None:
    world = make_world(three_events())
    report = await run_job(world, max_events=2)
    assert report.truncated is True
    assert report.examined == 2


async def test_out_of_window_and_before_since_are_skipped_and_counted() -> None:
    container = three_events()
    add_event(container, model_call("old", event_time="2026-01-01T01:00:00.000Z", span_id="a" * 16))
    world = make_world(container)
    report = await run_job(world, since=datetime(2026, 10, 2, tzinfo=UTC))
    assert report.matched == 4
    assert report.skipped_out_of_window == 2  # the January event and 2026-10-01
    assert report.reapplied == 2


async def test_other_source_or_external_id_is_not_matched() -> None:
    container = three_events()
    add_event(container, model_call("x", external_agent_id="someone-else", span_id="b" * 16))
    add_event(container, model_call("y", source_id="other-source", span_id="c" * 16))
    report = await run_job(make_world(container))
    assert report.examined == 5
    assert report.matched == 3


async def test_refuses_without_customer() -> None:
    world = make_world(three_events())
    with pytest.raises(ReresolveError):
        await run_job(world, customer_id="  ")


async def test_foreign_customer_record_is_never_processed() -> None:
    container = three_events()
    add_event(container, model_call("f1", customer_id="other", span_id="d" * 16))
    # message says another customer: the archive reader refuses it outright
    add_event(container, model_call("f2", span_id="e" * 16), message_customer="other")
    world = make_world(container)
    report = await run_job(world)
    assert report.skipped_foreign_customer == 1
    assert report.skipped_unreadable == 1
    assert report.matched == 3
    assert not any(
        c.startswith("event-") and "f1" in c for c in world.store.contributions(CUSTOMER)
    )
    assert len(world.store.contributions(CUSTOMER)) == 3


# ---------------------------------------------------------------------------------------- CLI


def test_cli_parses_exact_flags() -> None:
    args = build_arg_parser().parse_args(
        [
            "reresolve",
            "--customer",
            "synthco",
            "--source-id",
            SOURCE,
            "--external-agent-id",
            EXTERNAL,
            "--since",
            "2026-10-02T00:00:00Z",
            "--max-events",
            "7",
        ]
    )
    assert (args.customer, args.source_id, args.external_agent_id, args.max_events) == (
        "synthco",
        SOURCE,
        EXTERNAL,
        7,
    )
    assert args.since == datetime(2026, 10, 2, tzinfo=UTC)


async def _unwired() -> ReresolveDependencies:
    raise DependenciesNotWiredError("nope")


def test_cli_refuses_without_customer_and_on_bad_args(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["reresolve", "--source-id", SOURCE, "--external-agent-id", EXTERNAL]
    assert main(base, builder=_unwired) == EXIT_USAGE
    assert main(["reresolve", "--customer", "c"], builder=_unwired) == EXIT_USAGE
    assert main([*base, "--customer", "c", "--since", "yesterday"], builder=_unwired) == EXIT_USAGE
    assert "refused" in capsys.readouterr().err


def test_cli_reports_unwired_dependencies() -> None:
    argv = ["reresolve", "--customer", "c", "--source-id", SOURCE, "--external-agent-id", EXTERNAL]
    assert main(argv, builder=_unwired) == EXIT_NOT_WIRED


def test_cli_runs_with_injected_dependencies(capsys: pytest.CaptureFixture[str]) -> None:
    world = make_world(three_events())

    async def build() -> ReresolveDependencies:
        return ReresolveDependencies(
            world.reader, world.store, world.aggregates, world.catalog, world.resolver.stats
        )

    argv = [
        "reresolve",
        "--customer",
        CUSTOMER,
        "--source-id",
        SOURCE,
        "--external-agent-id",
        EXTERNAL,
    ]
    assert main(argv, builder=build) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] == 3
    assert report["reapplied"] + report["skipped_out_of_window"] == 3
    assert main([*argv, "--max-events", "1"], builder=build) == EXIT_TRUNCATED
