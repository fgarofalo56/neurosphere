"""Dashboards and reconciliation latency over a 90-day sandbox-sized dataset (PRP-14 item 5).

MEASURED, never asserted. What this is: wall-clock p50/p95/max of the dashboards endpoints (cost,
latency, errors, coverage at the day grain over 90 days and at the hour grain over 14 days) and
the reconciliation endpoint, called through the real FastAPI app (auth, scope derivation, router,
aggregate reader, response model) over an in-process ASGI transport, next to the server's own
``Server-Timing`` figure. The documents are produced by the real worker rollup code from
synthetic ledger entries and ``model_call`` spans, one domain per sandbox-style domain id.

What this is not: a performance claim. The PRD p95 <= 2 s figure is a planning target, "target,
not a guarantee"; it is recorded next to the numbers, never asserted. The in-memory store scans
documents with no index; the Cosmos variant runs against the compose vNext emulator, which has no
RU accounting and no range/composite indexes (gate G12), and Entra is not involved (the harness
validates dev-issuer tokens in memory). Sized-profile and cost evidence stay OPEN (G07, PRP-21).
So these numbers narrow the dashboard planning target only for this shape of data.

The in-memory test is unmarked (runs in CI); the emulator variant is marked ``integration``.
Knobs (defaults are small): ``NS_DASHBOARDS_LATENCY_ITERATIONS`` (20), ``..._DOMAINS`` (3),
``..._REQUESTS_PER_DAY`` (2). Results: ``temp/dashboards_latency/`` (gitignored).
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import platform
import random
import sys
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
for _extra in (ROOT, ROOT / "services" / "api" / "tests"):
    if str(_extra) not in sys.path:  # sandbox/ is a top-level package; authz harness lives here
        sys.path.insert(0, str(_extra))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
from neurosphere_api.dashboards import PREFIX as DASHBOARDS_PREFIX  # noqa: E402
from neurosphere_api.dashboards import get_clock  # noqa: E402
from neurosphere_api.reconciliation import PREFIX as RECONCILIATION_PREFIX  # noqa: E402
from neurosphere_api.reconciliation import get_now  # noqa: E402
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent  # noqa: E402
from neurosphere_core.aggregates import (  # noqa: E402
    AggregateReader,
    AggregateStatus,
    AggregateStore,
    Contribution,
    Grain,
    InMemoryAggregateStore,
    bucket_start,
    format_bucket,
)
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.ledger import Observation, PriceTable, PriceVersion, fold_entry  # noqa: E402
from neurosphere_workers.aggregates import (  # noqa: E402
    contribution_from_entry,
    contribution_from_event,
    hour_floor,
    rollup_bucket,
)

from sandbox.config import (  # noqa: E402
    PRICE_EFFECTIVE_DATE,
    PRICE_VERSION,
    PROFILES,
    GenerateConfig,
    with_overrides,
)
from sandbox.world import World  # noqa: E402

LABEL = "sandbox on compose, emulators; bounded feasibility"
TARGET_MS = 2000.0
TARGET_LABEL = (
    "PRD planning target (dashboard p95 <= 2 s on bounded 90-day aggregates): "
    "target, not a guarantee"
)
ITERATIONS = int(os.environ.get("NS_DASHBOARDS_LATENCY_ITERATIONS", "20"))
DOMAINS = int(os.environ.get("NS_DASHBOARDS_LATENCY_DOMAINS", "3"))
REQUESTS_PER_DAY = int(os.environ.get("NS_DASHBOARDS_LATENCY_REQUESTS_PER_DAY", "2"))
RESULT_DIR = ROOT / "temp" / "dashboards_latency"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CUSTOMER = helpers.CUSTOMER
WINDOW_DAYS = 90
HOUR_DAYS = 14
CATEGORY = "model_inference"
PRICES = PriceTable(
    [
        PriceVersion(
            price_version_id=PRICE_VERSION,
            effective_date=date.fromisoformat(PRICE_EFFECTIVE_DATE),
            currency="USD",
            source="synthetic",
            rates=[],
        )
    ]
)
PRICE_DATES = {v.price_version_id: v.effective_date for v in PRICES.versions}

# (name, kind, path suffix, query). Reconciliation has no grain: it is the daily rollup.
WORKLOADS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    *(
        (f"{m}_day_90d", f"{m}", {"days": 90, "grain": "day"})
        for m in ("cost", "latency", "errors", "coverage")
    ),
    *(
        (f"{m}_hour_14d", f"{m}", {"days": 14, "grain": "hour"})
        for m in ("cost", "latency", "errors", "coverage")
    ),
    ("reconciliation_day_90d", "reconciliation", {"days": 90}),
)


def _domain_ids() -> list[str]:
    """Domain ids from the sandbox generator's world plan, for the authz harness customer."""
    profile = with_overrides(PROFILES["tiny"], domains=max(1, DOMAINS))
    world = World(GenerateConfig(seed=7, profile=profile, cloud="commercial", customer=CUSTOMER))
    return [world.domain_id(i) for i in range(len(world.domains))]


# -- dataset ------------------------------------------------------------------------------------


@dataclass
class Dataset:
    buckets: list[tuple[str, Grain, str, list[Any]]]  # (domain, grain, bucket start, docs)
    status: AggregateStatus
    counts: dict[str, int]


def _event(domain: str, n: int, at: datetime, rng: random.Random) -> TelemetryEvent:
    roll = rng.random()
    outcome = "error" if roll < 0.05 else "unknown" if roll < 0.08 else "success"
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": f"evt-{uuid.uuid5(uuid.NAMESPACE_URL, f'{domain}/{n}').hex}",
        "event_time": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": "sandbox-gateway",
        "span_kind": "model_call",
        "outcome": outcome,
        "domain_id": domain,
    }
    if rng.random() > 0.1:  # ~10% of spans carry no duration: latency unknown, never 0
        body["duration_ms"] = int(rng.lognormvariate(5.5, 0.6))
    return TelemetryEvent.model_validate(body)


def _entry_and_event(
    domain: str, n: int, at: datetime, rng: random.Random
) -> tuple[Contribution, Contribution | None]:
    def obs(source: str, kind: str, amount: Decimal | None, offset: int, index: int) -> Observation:
        return Observation(
            observation_kind=source,  # type: ignore[arg-type]
            doc_id=f"{n * 4 + index:064x}",
            kind=kind,  # type: ignore[arg-type]
            amount=amount,
            currency="USD" if amount is not None else None,
            price_version_id=PRICE_VERSION if kind == "estimated" else None,
            price_unresolved=False,
            observed_at=at + timedelta(seconds=offset),
            cloud="commercial",
            source_id="sandbox-" + source,
            domain_id=domain,
        )

    known = rng.random() > 0.1  # ~10% of requests have no resolvable amount: unknown, not 0
    amount = Decimal(f"{rng.uniform(0.0001, 0.02):.6f}") if known else None
    observations = [obs("gateway", "estimated", amount, 1, 0)]
    if rng.random() < 0.8:
        observations.append(obs("application", "estimated", amount, 2, 1))
    if rng.random() < 0.5:
        observations.append(
            obs(
                "billing", "invoiced", None if amount is None else amount * Decimal("1.05"), 3600, 2
            )
        )
    entry = fold_entry(CUSTOMER, f"req-{domain[-3:]}-{n}", CATEGORY, observations)
    event = _event(domain, n, at, rng)
    return (
        contribution_from_entry(entry),
        contribution_from_event(CUSTOMER, f"{n:064x}", event),
    )


def build_dataset(domains: list[str], per_day: int) -> Dataset:
    """90 days of daily and 14 days of hourly rollups per domain, via the real rollup code."""
    rng = random.Random(7)
    by_bucket: dict[tuple[str, Grain, datetime], list[Contribution]] = {}
    floor = hour_floor(NOW)
    n = 0
    requests = 0
    watermark = ""
    billing = ""
    for domain in domains:
        for age in range(WINDOW_DAYS):
            day = bucket_start(NOW - timedelta(days=age), "day")
            moments = [
                day + timedelta(hours=(7 + 5 * i) % 24, minutes=3 * i) for i in range(per_day)
            ]
            if age < HOUR_DAYS:
                moments += [day + timedelta(hours=h, minutes=17) for h in range(24)]
            for moment in moments:
                if moment > NOW:
                    continue
                n += 1
                requests += 1
                for contribution in _entry_and_event(domain, n, moment, rng):
                    if contribution is None:
                        continue
                    by_bucket.setdefault((domain, "day", day), []).append(contribution)
                    hour = bucket_start(moment, "hour")
                    if hour >= floor:
                        by_bucket.setdefault((domain, "hour", hour), []).append(contribution)
                    watermark = max(watermark, contribution.observed_at or "")
                    billing = max(billing, contribution.billing_observed_at or "")
    buckets: list[tuple[str, Grain, str, list[Any]]] = []
    counts: Counter[str] = Counter()
    for (domain, grain, start), members in sorted(by_bucket.items()):
        docs = rollup_bucket(CUSTOMER, domain, grain, start, members, PRICE_DATES)
        buckets.append((domain, grain, format_bucket(start), docs))
        for doc in docs:
            counts[f"{grain}:{doc.metric}"] += 1
    counts["requests"] = requests
    status = AggregateStatus(
        customer_id=CUSTOMER, watermark=watermark or None, billing_observed_at=billing or None
    )
    return Dataset(buckets=buckets, status=status, counts=dict(counts))


async def load(store: AggregateStore, dataset: Dataset) -> None:
    for domain, grain, start, docs in dataset.buckets:
        await store.replace_bucket(CUSTOMER, domain, grain, start, docs)
    await store.put_status(dataset.status)


# -- measurement --------------------------------------------------------------------------------


def _percentile(sorted_ms: list[float], pct: float) -> float:
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_ms)))
    return sorted_ms[rank - 1]


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "samples": float(len(ordered)),
        "p50_ms": round(_percentile(ordered, 50), 3),
        "p95_ms": round(_percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
    }


def server_timing_ms(header: str | None) -> float | None:
    """``app;dur=12.3`` -> 12.3 (None when the header is absent or malformed)."""
    if not header:
        return None
    for part in header.split(","):
        fields = [f.strip() for f in part.split(";")]
        if fields[0] == "app":
            for field in fields[1:]:
                if field.startswith("dur="):
                    try:
                        return float(field[4:])
                    except ValueError:
                        return None
    return None


@asynccontextmanager
async def api_client(reader: AggregateReader, domains: list[str]) -> AsyncIterator[Any]:
    """The default app (dashboards and reconciliation come from ``REGISTERED``) with the harness
    auth, ``reader`` as ``app.state.aggregate_reader`` and a fixed clock."""
    h = helpers.harness(
        helpers.policy(
            helpers.ALICE,
            helpers.role(Role.VIEWER, *domains),
            memberships=tuple(domains),
        ),
        helpers.policy(helpers.BOB, helpers.role(Role.VIEWER, helpers.OPERATIONS)),
        routers={},
    )
    h.app.state.aggregate_reader = reader
    h.app.dependency_overrides[get_clock] = lambda: lambda: NOW
    h.app.dependency_overrides[get_now] = lambda: NOW
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=h.app), base_url="http://dashboards.invalid"
    ) as client:
        yield h, client


async def measure(
    reader: AggregateReader, domains: list[str], backend: str, dataset: Dataset
) -> dict[str, Any]:
    store_label = backend
    measured: dict[str, dict[str, Any]] = {}
    violations: list[str] = []
    async with api_client(reader, domains) as (h, client):
        headers = h.auth(helpers.ALICE)
        for name, kind, query in WORKLOADS:
            wall: list[float] = []
            server: list[float] = []
            series_seen: list[int] = []
            for index in range(ITERATIONS):
                domain = domains[index % len(domains)]
                path = (
                    f"{RECONCILIATION_PREFIX}/domains/{domain}"
                    if kind == "reconciliation"
                    else f"{DASHBOARDS_PREFIX}/domains/{domain}/{kind}"
                )
                started = time.perf_counter()
                response = await client.get(path, params=query, headers=headers)
                wall.append((time.perf_counter() - started) * 1000.0)
                assert response.status_code == 200, (name, response.status_code, response.text)
                body = response.json()
                if body["domain_id"] != domain:
                    violations.append(f"{name}: {body['domain_id']} != {domain}")
                timing = server_timing_ms(response.headers.get("Server-Timing"))
                if timing is not None:
                    server.append(timing)
                series_seen.append(len(body.get("series", body.get("sources", []))))
            entry: dict[str, Any] = {
                "wall_clock": _stats(wall),
                "series_or_sources_returned": min(series_seen),
            }
            if server:
                entry["server_timing_app"] = _stats(server)
            measured[name] = entry
        # A domain the viewer does not hold is refused, not served empty.
        denied = await client.get(
            f"{DASHBOARDS_PREFIX}/domains/{helpers.FINANCE}/cost", headers=headers
        )
    dataset_info = {
        "generator": "worker rollup_bucket over synthetic ledger entries and model_call spans",
        "domains": len(domains),
        "window_days": WINDOW_DAYS,
        "hour_grain_days": HOUR_DAYS,
        "requests_per_domain_day": REQUESTS_PER_DAY,
        "documents_by_grain_metric": dataset.counts,
        "documents_total": sum(len(b[3]) for b in dataset.buckets),
        "domain_ids_from": "sandbox World plan (tiny profile, domains overridden)",
    }
    return {
        "label": LABEL,
        "backend": store_label,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "target_ms_for_context_only": TARGET_MS,
        "target_label": TARGET_LABEL,
        "disclaimer": (
            "Measured on a developer machine through an in-process ASGI transport with dev-issuer "
            "tokens validated in memory. RU accounting, range/composite indexing and Entra are not "
            "reproduced (G12). This narrows the dashboard planning target only; sized-profile and "
            "cost evidence stay OPEN (G07, PRP-21). Not a guarantee or an SLA."
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "dataset": dataset_info,
        "iterations_per_workload": ITERATIONS,
        "workloads": measured,
        "p95_wall_clock_ms_by_workload": {
            k: v["wall_clock"]["p95_ms"] for k, v in measured.items()
        },
        "p95_vs_target": {
            k: {
                "p95_ms": v["wall_clock"]["p95_ms"],
                "target_ms": TARGET_MS,
                "ratio_of_target": round(v["wall_clock"]["p95_ms"] / TARGET_MS, 4),
            }
            for k, v in measured.items()
        },
        "scope_violations": violations,
        "foreign_domain_status": denied.status_code,
    }


def _report(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\ndashboards latency ({LABEL}; backend {result['backend']})")
    print(f"  {TARGET_LABEL}; NOT asserted")
    for name, stats in result["workloads"].items():
        wall = stats["wall_clock"]
        srv = stats.get("server_timing_app", {})
        print(
            f"  {name:24s} wall p50={wall['p50_ms']:8.3f} p95={wall['p95_ms']:8.3f} "
            f"max={wall['max_ms']:8.3f} ms | server p95={srv.get('p95_ms', float('nan')):8.3f} ms "
            f"n={int(wall['samples'])}"
        )
    print(f"  recorded: {path}")


def _check(result: dict[str, Any]) -> None:
    assert result["scope_violations"] == []
    assert result["foreign_domain_status"] == 403
    assert result["label"] == LABEL
    assert set(result["workloads"]) == {name for name, _, _ in WORKLOADS}
    for name, stats in result["workloads"].items():
        assert stats["series_or_sources_returned"] >= 1, f"{name} returned nothing to time"
        assert stats["wall_clock"]["p95_ms"] > 0
        assert "server_timing_app" in stats, f"{name}: no Server-Timing header"


def test_dashboards_latency_is_measured_and_recorded_in_memory() -> None:
    domains = _domain_ids()
    store = InMemoryAggregateStore()
    dataset = build_dataset(domains, REQUESTS_PER_DAY)
    assert dataset.counts["requests"] > 0
    result = asyncio.run(_run_in_memory(store, domains, dataset))
    _check(result)
    _report(result, RESULT_DIR / "p95.json")
    assert (RESULT_DIR / "p95.json").is_file()


async def _run_in_memory(
    store: InMemoryAggregateStore, domains: list[str], dataset: Dataset
) -> dict[str, Any]:
    await load(store, dataset)
    return await measure(store, domains, "InMemoryAggregateStore", dataset)


# -- compose Cosmos emulator ---------------------------------------------------------------------


@pytest.mark.integration
def test_dashboards_latency_is_measured_and_recorded_on_the_cosmos_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    result = asyncio.run(_run_emulator())
    _check(result)
    _report(result, RESULT_DIR / "p95_emulator.json")


async def _run_emulator() -> dict[str, Any]:
    from azure.cosmos import PartitionKey
    from neurosphere_core.aggregates.cosmos import PARTITION_KEY_PATH, CosmosAggregateStore
    from neurosphere_core.clients import ClientLifetime, create_cosmos_client
    from neurosphere_core.cloud import Settings

    domains = _domain_ids()[:1]  # the emulator is slow to load; one domain keeps the run bounded
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        database = await client.create_database_if_not_exists("ns_aggregates_it")
        name = f"agg_lat_{uuid.uuid4().hex[:10]}"
        container = await database.create_container_if_not_exists(
            id=name, partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        try:
            store = CosmosAggregateStore(container)
            loaded = time.perf_counter()
            dataset = build_dataset(domains, REQUESTS_PER_DAY)
            await load(store, dataset)
            load_seconds = time.perf_counter() - loaded
            result = await measure(
                store, domains, "CosmosAggregateStore (compose vNext emulator)", dataset
            )
            result["dataset"]["emulator_load_seconds"] = round(load_seconds, 1)
            return result
        finally:
            await database.delete_container(name)
