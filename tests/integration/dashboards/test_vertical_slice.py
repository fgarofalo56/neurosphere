"""Vertical slice, in process, on the compose emulators (PRP-14 item 5).

sandbox generator -> ingest edge (CloudEvents) -> Event Hubs -> normalizer -> Cosmos ledger and
outbox -> the item 1 aggregates handler draining the outbox into a Cosmos aggregates container
(unique per run) -> dashboards and reconciliation API over an httpx ASGI transport with
``app.state.aggregate_reader`` set. One expensive run per module; each test asserts one aspect.

Expected values come from the raw sandbox bundle and from the ledger documents read straight from
Cosmos, never from the aggregates under test.

What this proves: the slice end to end on emulators, unknown is never 0, estimated and invoiced
stay separate, price versions are cited, each request is counted once, scope denial returns 403,
and the API keeps serving when the analytics adapter is absent, stopped or raising.

What it does NOT prove (recorded OPEN): browser e2e against compose in CI, hosting the aggregates
worker in the compose ``workers`` container, a production ``TraceEventSource`` (this module
supplies a test-local one over the archive), a production bootstrap of ``aggregate_reader``, RU
accounting, range/composite indexes and Entra (G12), and sized-profile evidence (G07, PRP-21).
"""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import httpx
import pytest
import pytest_asyncio
from azure.cosmos import PartitionKey
from neurosphere_api.dashboards import PREFIX as DASHBOARDS_PREFIX
from neurosphere_api.dashboards import get_clock
from neurosphere_api.reconciliation import PREFIX as RECONCILIATION_PREFIX
from neurosphere_api.reconciliation import get_now
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.aggregates import parse_time
from neurosphere_core.aggregates.cosmos import PARTITION_KEY_PATH, CosmosAggregateStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import LedgerEntry, PriceTable, PriceVersion, TimeWindow
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_workers.aggregates import AggregateProjection, StoreLedgerSource
from neurosphere_workers.projections.catalog import LoadedEvent
from neurosphere_workers.projections.outbox import (
    SINK_AGGREGATES,
    CosmosCheckpointStore,
    CosmosOutboxStore,
    OutboxReader,
)

from integration.ingestion.conftest import _emulator_env, fresh_hub  # noqa: F401
from integration.ingestion.support import (
    REPO_ROOT,
    Pipeline,
    Producer,
    cloudevent,
    edge_client,
    push_cloudevents,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

CUSTOMER = helpers.CUSTOMER  # the authz harness customer; the bundle is renamed to it
GENERATED_CUSTOMER = "synthco"  # the generator's fixed customer
SEED = 7
LAG_SECONDS = 120.0
PRICE_VERSION_ID = "sandbox-prices-2026-10"  # the sandbox price sheet's version (sandbox/config.py)
PRICE_EFFECTIVE = date(2026, 10, 1)
PRICES = PriceTable(
    [
        PriceVersion(
            price_version_id=PRICE_VERSION_ID,
            effective_date=PRICE_EFFECTIVE,
            currency="USD",
            source="synthetic",
            rates=[],
        )
    ]
)

Doc = dict[str, Any]


def domain_of(index: int) -> str:
    return f"commercial:{CUSTOMER}:sandbox:domain:dom-{index:03d}"


DOMAIN_A, DOMAIN_B = domain_of(1), domain_of(2)


# -- test-local pieces --------------------------------------------------------------------------


class ArchiveEventSource:
    """``TraceEventSource`` over the redacted archive blobs of this run (test-local: the product
    has no archive reader yet, which is why latency and errors have no production source)."""

    def __init__(self, events: dict[str, LoadedEvent]) -> None:
        self._events = events

    @classmethod
    def from_archive(cls, records: dict[str, Doc]) -> ArchiveEventSource:
        events: dict[str, LoadedEvent] = {}
        for name, record in records.items():
            doc_id = name.rsplit("/", 1)[-1].removesuffix(".json.gz")
            try:
                events[doc_id] = LoadedEvent(
                    doc_id=doc_id, event=TelemetryEvent.model_validate(record["contract"])
                )
            except ValueError:
                continue  # a cost record: the aggregates read those through the ledger
        return cls(events)

    async def get_event(self, customer_id: str, doc_id: str) -> LoadedEvent | None:
        loaded = self._events.get(doc_id)
        if loaded is None or loaded.event.customer_id.root != customer_id:
            return None
        return loaded

    async def find_span(self, customer_id: str, trace_id: str, span_id: str) -> LoadedEvent | None:
        return None

    async def find_child_spans(
        self, customer_id: str, trace_id: str, parent_span_id: str
    ) -> Sequence[LoadedEvent]:
        return []

    def __len__(self) -> int:
        return len(self._events)


class AdapterStub:
    """A sandbox-only analytics adapter identity (``fixture`` backend) for the state probe."""

    backend = "fixture"
    cloud = "commercial"


async def _stopped() -> bool:
    return False


async def _raising() -> bool:
    raise ConnectionError("analytics endpoint refused")


async def _healthy() -> bool:
    return True


# -- the run ------------------------------------------------------------------------------------


@dataclass
class SliceRun:
    pipe: Pipeline
    store: CosmosAggregateStore
    h: Any
    client: httpx.AsyncClient
    telemetry: list[Doc]
    costs: list[Doc]
    entries: list[LedgerEntry]
    expected_requests: dict[str, set[str]]
    cost_observations: Counter[str]
    watermark: str
    pushed: int
    consumer_counts: dict[str, int]
    drained: int
    stats: Any
    quarantined: dict[str, int] = field(default_factory=dict)

    def get(self, who: str | None, path: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.client.get(path, params=params or None, headers=headers)

    def dashboard(self, who: str | None, domain: str, metric: str, **params: Any) -> Any:
        return self.get(who, f"{DASHBOARDS_PREFIX}/domains/{domain}/{metric}", **params)

    def reconciliation(self, who: str | None, domain: str, **params: Any) -> Any:
        return self.get(who, f"{RECONCILIATION_PREFIX}/domains/{domain}", **params)


def _read_bundle(directory: Path, name: str) -> list[Doc]:
    docs: list[Doc] = []
    for line in (directory / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            docs.append(json.loads(line.replace(GENERATED_CUSTOMER, CUSTOMER)))
    return docs


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clean seeded sandbox bundle (exact duplicates only, some optional fields missing)."""
    out = tmp_path_factory.mktemp("dash-sandbox")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sandbox.generate",
            "--seed",
            str(SEED),
            "--profile",
            "tiny",
            "--traces-per-agent-day",
            "2",
            "--duplicate-rate",
            "0.05",
            "--out-of-order-rate",
            "0",
            "--malformed-rate",
            "0",
            "--missing-optional-rate",
            "0.15",
            "--cloud",
            "commercial",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return out


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _latest_time(telemetry: Iterable[Doc], costs: Iterable[Doc]) -> datetime:
    stamps = [_parse(t["event_time"]) for t in telemetry]
    for cost in costs:
        stamps.extend(_parse(cost[k]) for k in ("recorded_at", "usage_end") if cost.get(k))
    return max(stamps)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def run(bundle: Path, tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[SliceRun]:
    telemetry = _read_bundle(bundle, "telemetry.ndjson")
    costs = _read_bundle(bundle, "cost.ndjson")
    settings = Settings(env="local")
    producers = [
        Producer("p-gw", CUSTOMER, "commercial", {"sandbox-gateway": "gateway"}),
        Producer("p-app", CUSTOMER, "commercial", {"sandbox-application": "application"}),
        Producer("p-bill", CUSTOMER, "commercial", {"sandbox-billing": "billing"}),
    ]
    by_id = {p.producer_id: p for p in producers}
    owner = {"sandbox-gateway": "p-gw", "sandbox-application": "p-app", "sandbox-billing": "p-bill"}

    # The request each cost record belongs to, and the oracle of distinct requests per domain.
    request_of_event = {
        t["event_id"]: t["request_id"]
        for t in telemetry
        if t.get("span_kind") == "model_call" and t.get("request_id")
    }
    expected: dict[str, set[str]] = defaultdict(set)
    observations: Counter[str] = Counter()
    for t in telemetry:
        if t.get("span_kind") == "model_call" and t.get("request_id") and t.get("domain_id"):
            expected[t["domain_id"]].add(t["request_id"])
    cost_events: dict[str, list[Doc]] = {"p-gw": [], "p-app": [], "p-bill": []}
    for cost in costs:
        first = cost["event_ids"][0]
        request_id = request_of_event.get(first, f"req-{first}")
        cost_events[owner[cost["source_id"]]].append(
            cloudevent("cost", cost, request_id=request_id)
        )
        if cost.get("domain_id"):
            expected[cost["domain_id"]].add(request_id)
            observations[cost["domain_id"]] += 1

    async with Pipeline.open(settings) as pipe:
        edge_dir = tmp_path_factory.mktemp("dash-edge")
        pushed = 0
        async with edge_client(settings, producers, edge_dir) as edge:
            events = [cloudevent("telemetry", t) for t in telemetry]
            tel_push = await push_cloudevents(edge, by_id["p-gw"], events)
            assert tel_push.rejected_indexes == [], "the clean bundle must not be rejected"
            pushed += tel_push.sent
            for key in ("p-gw", "p-app", "p-bill"):
                cost_push = await push_cloudevents(edge, by_id[key], cost_events[key])
                assert cost_push.rejected_indexes == []
                pushed += cost_push.sent
        consumer = await pipe.consume(expect_processed=pushed)
        assert consumer.processed == pushed
        assert sum(consumer.quarantined.values()) == 0, dict(consumer.quarantined)
        # The outbox hides entries younger than its settle window; wait it out, then read.
        await asyncio.sleep(3.0)

        # -- the ledger, read straight from Cosmos: the oracle for the aggregates -----------
        ledger_store = CosmosLedgerStore(
            pipe.database.get_container_client(pipe.ledger.ledger_container)
        )
        entries = await ledger_store.list_entries(
            CUSTOMER, TimeWindow(datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
        )

        # -- aggregates: item 1 handler draining the outbox into a unique Cosmos container --
        agg_container = await pipe.database.create_container_if_not_exists(
            id=f"agg_{pipe.run}", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        store = CosmosAggregateStore(agg_container)
        archive = await pipe.archive_records(CUSTOMER)
        projection_now = _latest_time(telemetry, costs) + timedelta(days=1)
        projection = AggregateProjection(
            store=store,
            ledger=StoreLedgerSource(ledger_store),
            events=ArchiveEventSource.from_archive(archive),
            prices=PRICES,
            clock=lambda: projection_now,
        )
        reader = OutboxReader(
            CosmosOutboxStore(
                pipe.database.get_container_client(pipe.ledger.outbox_container),
                settle_seconds=2,
            ),
            CosmosCheckpointStore(
                pipe.database.get_container_client(pipe.ledger.checkpoint_container)
            ),
            batch_size=200,
        )
        drained = await reader.drain(SINK_AGGREGATES, CUSTOMER, projection)
        assert drained.ok, drained
        status = await store.status(CUSTOMER)
        assert status is not None and status.watermark is not None
        api_now = parse_time(status.watermark) + timedelta(seconds=LAG_SECONDS)

        # -- the API: default routers from REGISTERED, harness auth, httpx ASGI ----------------
        h = helpers.harness(
            helpers.policy(
                helpers.ALICE, helpers.role(Role.VIEWER, DOMAIN_A), memberships=(DOMAIN_A,)
            ),
            helpers.policy(
                helpers.BOB, helpers.role(Role.VIEWER, DOMAIN_B), memberships=(DOMAIN_B,)
            ),
            routers={},
        )
        h.app.state.aggregate_reader = store
        h.app.dependency_overrides[get_clock] = lambda: lambda: api_now
        h.app.dependency_overrides[get_now] = lambda: api_now
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.app), base_url="http://dashboards.invalid"
        ) as client:
            yield SliceRun(
                pipe=pipe,
                store=store,
                h=h,
                client=client,
                telemetry=telemetry,
                costs=costs,
                entries=entries,
                expected_requests=dict(expected),
                cost_observations=observations,
                watermark=status.watermark,
                pushed=pushed,
                consumer_counts={
                    "accepted": consumer.accepted,
                    "duplicates": consumer.duplicates,
                    "late": consumer.late,
                },
                drained=drained.delivered,
                stats=projection.stats,
            )


# -- helpers ------------------------------------------------------------------------------------


def walk_values(node: Any) -> Iterable[dict[str, Any]]:
    """Every MetricValue-shaped dict (value/status/complete) anywhere in a response body."""
    if isinstance(node, dict):
        if {"value", "status", "complete"} <= node.keys():
            yield node
        for child in node.values():
            yield from walk_values(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk_values(child)


def series_by_key(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in body["series"]}


def nearest_rank(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100.0 * len(ordered))) - 1]


def domain_entries(run: SliceRun, domain: str) -> list[LedgerEntry]:
    return [e for e in run.entries if e.domain_id == domain]


# -- the pipeline -------------------------------------------------------------------------------


async def test_the_pipeline_processed_everything_and_the_outbox_drained(run: SliceRun) -> None:
    counts = run.consumer_counts
    assert counts["accepted"] + counts["duplicates"] == run.pushed
    assert counts["duplicates"] > 0, "the bundle carries exact duplicates; dedupe must show"
    assert run.drained > 0
    assert run.stats.applied > 0
    # Request ids are the ledger's key: one entry per distinct request, per domain.
    assert run.entries
    for domain, requests in run.expected_requests.items():
        assert {e.request_id for e in domain_entries(run, domain)} == requests, domain


async def test_each_request_is_counted_once_in_the_reconciliation_reference(run: SliceRun) -> None:
    response = await run.reconciliation(helpers.ALICE, DOMAIN_A, days=30)
    assert response.status_code == 200, response.text
    body = response.json()
    requests = run.expected_requests[DOMAIN_A]
    counted = sum(line["entry_count"] for line in body["references"])
    assert counted == len(requests)
    # More observations than requests were ingested (gateway + application + billing), so a
    # naive sum over observations would double count; the reference does not.
    assert run.cost_observations[DOMAIN_A] > len(requests)

    # The reference amount is the ledger's authoritative amount, summed by currency.
    oracle: dict[str, Decimal] = defaultdict(Decimal)
    unknown_entries = 0
    for entry in domain_entries(run, DOMAIN_A):
        if entry.authoritative_amount is None:
            unknown_entries += 1
        else:
            oracle[entry.authoritative_currency or "XXX"] += entry.authoritative_amount
    for line in body["references"]:
        currency = line["currency"]
        if currency in oracle and line["amount"]["status"] == "known":
            assert line["amount"]["value"] == pytest.approx(float(oracle[currency]), rel=1e-6)
    assert sum(line["unknown_entry_count"] for line in body["references"]) == unknown_entries
    assert body["disclaimer"] == "not_all_spend_observable"


async def test_reconciliation_reports_variance_per_source_with_granularity(run: SliceRun) -> None:
    response = await run.reconciliation(helpers.ALICE, DOMAIN_A, days=30)
    body = response.json()
    sources = {(s["source"], s["currency"]): s for s in body["sources"]}
    assert {s for s, _ in sources} >= {"gateway", "app", "billing"}
    for (_, _), line in sources.items():
        assert line["granularity"] in {"request", "vendor", "unknown"}
        if line["variance"]["status"] == "known":
            reference = next(r for r in body["references"] if r["currency"] == line["currency"])
            assert line["variance"]["value"] == pytest.approx(
                line["amount"]["value"] - reference["amount"]["value"], abs=1e-6
            )
        if line["coverage"]["status"] == "unknown":
            assert line["coverage"]["value"] is None  # unknown coverage is not 0 percent


# -- cost: separate series, price versions, unknown never 0 -------------------------------------


async def test_cost_keeps_estimated_and_invoiced_apart_and_cites_the_price_version(
    run: SliceRun,
) -> None:
    response = await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", days=30)
    assert response.status_code == 200, response.text
    body = response.json()
    by_key = series_by_key(body)
    kinds = {s["kind"] for s in body["series"]}
    assert kinds == {"estimated", "invoiced"}, "separate series, never a blended one (kind=None)"
    assert "estimated:USD" in by_key and "invoiced:USD" in by_key
    assert response.headers["Server-Timing"].startswith("app;dur=")

    # Totals equal the ledger's per-kind sums (known amounts only), measured independently.
    entries = domain_entries(run, DOMAIN_A)
    est = sum((e.estimated_amount for e in entries if e.estimated_amount is not None), Decimal(0))
    inv = sum((e.invoiced_amount for e in entries if e.invoiced_amount is not None), Decimal(0))
    assert by_key["estimated:USD"]["total"]["value"] == pytest.approx(float(est), rel=1e-6)
    assert by_key["invoiced:USD"]["total"]["value"] == pytest.approx(float(inv), rel=1e-6)
    assert by_key["estimated:USD"]["total"]["value"] != by_key["invoiced:USD"]["total"]["value"]

    # Every estimated figure cites the price version and its effective date.
    expected = {"id": PRICE_VERSION_ID, "effective_date": PRICE_EFFECTIVE.isoformat()}
    assert expected in body["price_versions"]
    assert by_key["estimated:USD"]["total"]["price_version"] == expected
    cited = [
        p["value"]["price_version"]
        for p in by_key["estimated:USD"]["points"]
        if p["value"]["status"] == "known"
    ]
    assert cited and all(pv == expected for pv in cited)


async def test_unknown_is_never_zero_anywhere(run: SliceRun) -> None:
    unknown_seen = 0
    for metric in ("cost", "latency", "errors", "coverage"):
        for grain, days in (("day", 30), ("hour", 14)):
            response = await run.dashboard(helpers.ALICE, DOMAIN_A, metric, days=days, grain=grain)
            assert response.status_code == 200, (metric, grain, response.text)
            for value in walk_values(response.json()):
                if value["status"] == "unknown":
                    unknown_seen += 1
                    assert value["value"] is None, (metric, value)
                    assert value["complete"] is False
                else:
                    assert value["value"] is not None
    assert unknown_seen > 0, "the slice must exercise unknown values"

    # Latency totals are unknown by design (percentiles do not combine), never 0.
    latency = (await run.dashboard(helpers.ALICE, DOMAIN_A, "latency", days=30)).json()
    assert {s["key"] for s in latency["series"]} == {"p50", "p95", "p99"}
    assert all(
        s["total"] == {**s["total"], "value": None, "status": "unknown"} for s in latency["series"]
    )

    # An entry with no known amount keeps the coverage honest (below 1) and the total incomplete.
    unknown_entries = [e for e in domain_entries(run, DOMAIN_A) if e.authoritative_amount is None]
    coverage = (await run.dashboard(helpers.ALICE, DOMAIN_A, "coverage", days=30)).json()
    value = series_by_key(coverage)["coverage:USD"]["total"]
    if unknown_entries:
        assert value["status"] == "known" and value["value"] < 1.0
        assert value["complete"] is False
    assert coverage["complete"] is False or not unknown_entries


# -- latency and errors from model_call spans (test-local trace source) -------------------------


async def test_latency_and_errors_match_the_model_call_spans_in_the_bundle(run: SliceRun) -> None:
    seen: set[str] = set()
    durations: dict[str, list[int]] = defaultdict(list)
    outcomes: dict[str, Counter[str]] = defaultdict(Counter)
    for t in run.telemetry:
        if t.get("span_kind") != "model_call" or t.get("domain_id") != DOMAIN_A:
            continue
        if t["event_id"] in seen:
            continue  # exact duplicates are dropped by the normalizer
        seen.add(t["event_id"])
        day = t["event_time"][:10]
        if t.get("duration_ms") is not None:
            durations[day].append(int(t["duration_ms"]))
        outcomes[day][t.get("outcome") or "unknown"] += 1
    assert durations, "the domain must have model_call spans with durations"

    latency = series_by_key(
        (await run.dashboard(helpers.ALICE, DOMAIN_A, "latency", days=30)).json()
    )
    for key, pct in (("p50", 50), ("p95", 95), ("p99", 99)):
        points = {p["t"][:10]: p["value"] for p in latency[key]["points"]}
        for day, values in durations.items():
            assert points[day]["status"] == "known", (key, day)
            assert points[day]["value"] == nearest_rank(values, pct), (key, day)

    errors = series_by_key((await run.dashboard(helpers.ALICE, DOMAIN_A, "errors", days=30)).json())
    for point in errors["error_count"]["points"]:
        counts = outcomes[point["t"][:10]]
        expected_errors = counts["error"] + counts["timeout"]
        assert point["value"]["value"] == expected_errors, point


# -- authorization ------------------------------------------------------------------------------


async def test_a_viewer_of_domain_a_never_receives_domain_b(run: SliceRun) -> None:
    for path in (
        f"{DASHBOARDS_PREFIX}/domains/{DOMAIN_B}/cost",
        f"{DASHBOARDS_PREFIX}/domains/{DOMAIN_B}/latency",
        f"{DASHBOARDS_PREFIX}/domains/{DOMAIN_B}/errors",
        f"{DASHBOARDS_PREFIX}/domains/{DOMAIN_B}/coverage",
        f"{RECONCILIATION_PREFIX}/domains/{DOMAIN_B}",
    ):
        response = await run.get(helpers.ALICE, path)
        assert response.status_code == 403, (path, response.status_code)  # not an empty 200
        assert DOMAIN_B not in response.text.replace(path, "")
    # The rightful viewer of B gets B's data, and none of A's.
    allowed = await run.dashboard(helpers.BOB, DOMAIN_B, "cost", days=30)
    assert allowed.status_code == 200
    assert allowed.json()["domain_id"] == DOMAIN_B
    assert DOMAIN_A not in allowed.text
    assert (await run.dashboard(helpers.BOB, DOMAIN_A, "cost")).status_code == 403
    # No token is a 401, and a caller-supplied scope parameter changes nothing.
    assert (await run.dashboard(None, DOMAIN_A, "cost")).status_code == 401
    sneaky = await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", domain_id=DOMAIN_B, days=30)
    assert sneaky.status_code == 200 and sneaky.json()["domain_id"] == DOMAIN_A


# -- freshness and analytics-down ---------------------------------------------------------------


async def test_freshness_reports_the_watermark_and_lag(run: SliceRun) -> None:
    body = (await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", days=30)).json()
    assert body["freshness"]["watermark"] == run.watermark
    assert body["freshness"]["lag_seconds"] == LAG_SECONDS
    assert body["freshness"]["billing_source_freshness"] is not None
    recon = (await run.reconciliation(helpers.ALICE, DOMAIN_A, days=30)).json()
    assert recon["freshness"]["lag_seconds"] == LAG_SECONDS


async def test_the_hour_grain_serves_and_a_wider_window_is_refused(run: SliceRun) -> None:
    ok = await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", days=14, grain="hour")
    assert ok.status_code == 200 and ok.json()["grain"] == "hour"
    too_wide = await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", days=30, grain="hour")
    assert too_wide.status_code == 422


async def _snapshot(run: SliceRun) -> tuple[dict[str, Any], list[Any]]:
    cost = (await run.dashboard(helpers.ALICE, DOMAIN_A, "cost", days=30)).json()
    recon = (await run.reconciliation(helpers.ALICE, DOMAIN_A, days=30)).json()
    return cost, [cost["series"], cost["price_versions"], recon["references"], recon["sources"]]


async def test_analytics_down_still_serves_from_the_aggregates(run: SliceRun) -> None:
    state = run.h.app.state
    baseline_body, baseline = await _snapshot(run)
    # No adapter configured: disabled with a reason, data intact.
    assert baseline_body["analytics"]["state"] == "disabled"
    assert baseline_body["analytics"]["reason"]
    assert baseline_body["series"], "dashboards still serve with no analytics backend"

    cases = (
        ("healthy", _healthy, "available"),
        ("stopped", _stopped, "disabled"),
        ("raising", _raising, "delayed"),
    )
    try:
        for label, health, expected_state in cases:
            state.analytics_adapter = AdapterStub()
            state.analytics_region = "eastus2"
            state.analytics_health = health
            body, snapshot = await _snapshot(run)
            assert body["analytics"]["state"] == expected_state, label
            assert snapshot == baseline, f"{label}: aggregates differ with the adapter {label}"
            if expected_state != "available":
                assert body["analytics"]["reason"], label
                for vendor in ("fabric", "synapse", "databricks"):
                    assert vendor not in json.dumps(body["analytics"]).lower()
    finally:
        for name in ("analytics_adapter", "analytics_region", "analytics_health"):
            if hasattr(state, name):
                delattr(state, name)

    # The aggregates never needed the adapter: unrelated to the adapter's state, a fresh read
    # after cleanup is identical again.
    again, after = await _snapshot(run)
    assert again["analytics"]["state"] == "disabled" and after == baseline


async def test_the_slice_run_is_isolated(run: SliceRun) -> None:
    """Unique names per run: the aggregates container and database belong to this run only."""
    assert run.pipe.run
    docs = [
        d
        async for d in run.pipe.database.get_container_client(f"agg_{run.pipe.run}").query_items(
            query="SELECT VALUE COUNT(1) FROM c WHERE c.doc_type = 'aggregate'",
            partition_key=CUSTOMER,
        )
    ]
    assert docs and docs[0] > 0
