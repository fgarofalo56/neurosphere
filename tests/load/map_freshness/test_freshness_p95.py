"""Event-to-view freshness of the live map under sandbox load (PRP-18 item 6).

MEASURED, never asserted against the target. The PRD figure "p95 event-to-view <= 10 s" is a
planning target ("target, not a guarantee"); it is recorded beside the measurement and
``meets_target`` is data, not a test condition. The tests assert correctness only: every event
became visible to every subscriber of its domain, and no subscriber ever received a delta for a
domain outside its scope.

Definition (exact):

* t0 = the instant (``time.perf_counter``) a synthetic normalized telemetry event is handed to the
  worker's aggregate rollup path, i.e. immediately before ``AggregateProjection.handle(entry)``
  is awaited for it. This is the REAL ``neurosphere_workers.aggregates`` handler and rollup code
  writing the REAL aggregate store (in-memory, or Cosmos on the compose vNext emulator).
* t1 = the instant (same clock) a subscribed WebSocket client receives a ``delta`` frame whose
  node ``frequency`` (the domain's request count in the current hour bucket) has reached that
  event's ordinal within its domain, so the frame's aggregates reflect the event.
* freshness = t1 - t0, one sample per (subscriber, event). Subscribers of one domain each yield a
  sample for every event of that domain.

Pipeline: synthetic events (domain ids from the sandbox generator's world plan, as
``dashboards_latency`` does) -> ``AggregateProjection.handle`` -> aggregate store ->
``AggregateDeltaSource`` polling (real ``RealtimeSettings`` poll interval and its half-interval
read cache) -> gateway pump/send-time scope filter -> WebSocket through the real FastAPI app with
dev-issuer tokens. Each subscriber is a principal whose scope holds ONE domain; it also tries to
subscribe to a second domain it does not hold (must be refused, and no delta for it may ever
arrive).

Exclusions (recorded in the JSON): Event Hubs transport and the ingest edge are NOT in the loop
(the emulator lacks Entra and the ingest edge is measured elsewhere; events enter at the
normalized, post-ingestion boundary); provider billing freshness (it lags by days, and the map
shows its watermark instead); Entra/JWKS (dev-issuer tokens validated in memory); network between
client and API (in-process ASGI); browser rendering (frame rate is a separate item); RU
accounting and indexing on a real Cosmos account (gate G12); a sized profile (G07, PRP-21).

The unmarked test runs in CI with the in-memory store; the emulator variant is marked
``integration`` and FAILS (never skips) when the emulator is unreachable.
Knobs (small defaults): ``NS_MAP_FRESHNESS_EVENTS_PER_SECOND`` (5),
``NS_MAP_FRESHNESS_DOMAINS`` (3), ``NS_MAP_FRESHNESS_DURATION_SECONDS`` (6),
``NS_MAP_FRESHNESS_SUBSCRIBERS`` (6, spread round-robin over the domains). The poll interval is
the product setting (``NS_REALTIME_POLL_INTERVAL_SECONDS``, default 2 s). Results:
``temp/map_freshness/`` (gitignored).
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio.from_thread
import pytest

ROOT = Path(__file__).resolve().parents[3]
for _extra in (ROOT, ROOT / "tests", ROOT / "services" / "api" / "tests"):
    if str(_extra) not in sys.path:  # sandbox/ is top-level; authz harness lives under api tests
        sys.path.insert(0, str(_extra))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # noqa: E402
from neurosphere_api.realtime import PREFIX as REALTIME_PREFIX  # noqa: E402
from neurosphere_api.realtime import RealtimeSettings, configure_realtime  # noqa: E402
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent  # noqa: E402
from neurosphere_core.aggregates import AggregateStore, InMemoryAggregateStore  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_workers.aggregates import AggregateProjection  # noqa: E402
from neurosphere_workers.projections.catalog import (  # noqa: E402
    InMemoryTraceEventSource,
    LoadedEvent,
)
from neurosphere_workers.projections.outbox.models import OutboxEntry  # noqa: E402
from starlette.testclient import WebSocketTestSession  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from sandbox.config import PROFILES, GenerateConfig, with_overrides  # noqa: E402
from sandbox.world import World  # noqa: E402

LABEL_EMULATOR = "sandbox on compose, emulators; bounded feasibility"
LABEL_MEMORY = "in-memory"
TARGET_SECONDS = 10.0
TARGET_LABEL = "PRD planning target (event-to-view freshness p95 <= 10 s): target, not a guarantee"
EVENTS_PER_SECOND = float(os.environ.get("NS_MAP_FRESHNESS_EVENTS_PER_SECOND", "5"))
DOMAINS = int(os.environ.get("NS_MAP_FRESHNESS_DOMAINS", "3"))
DURATION_SECONDS = float(os.environ.get("NS_MAP_FRESHNESS_DURATION_SECONDS", "6"))
SUBSCRIBERS = int(os.environ.get("NS_MAP_FRESHNESS_SUBSCRIBERS", "6"))
RESULT_DIR = ROOT / "temp" / "map_freshness"
CUSTOMER = helpers.CUSTOMER
REVOCATION_TTL_SECONDS = 10.0
WS_URL = f"{REALTIME_PREFIX}/ws"
EXCLUSIONS = [
    "Event Hubs transport and ingest edge (emulator lacks Entra; the edge is measured elsewhere):"
    " events enter at the normalized, post-ingestion boundary",
    "provider billing freshness (days of lag; the map shows the billing watermark instead)",
    "Entra / JWKS (dev-issuer tokens validated in memory)",
    "network between client and API (in-process ASGI transport and TestClient)",
    "browser rendering and frame rate (separate item)",
    "RU accounting, throttling and index policy of a real Cosmos account (G12)",
    "sized profiles and concurrency at production scale (G07, PRP-21)",
]


def _domain_ids() -> list[str]:
    """Domain ids from the sandbox generator's world plan, for the authz harness customer."""
    profile = with_overrides(PROFILES["tiny"], domains=max(1, DOMAINS))
    world = World(GenerateConfig(seed=7, profile=profile, cloud="commercial", customer=CUSTOMER))
    return [world.domain_id(i) for i in range(len(world.domains))]


# -- environment --------------------------------------------------------------------------------


def _cpu_model() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _ram_gib() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem = _Mem()
            mem.dwLength = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))  # type: ignore[attr-defined]
            return round(mem.ullTotalPhys / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (OSError, ValueError, AttributeError):
        return None


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# -- statistics ---------------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: float) -> float:
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[rank - 1]


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "p50_seconds": round(_percentile(ordered, 50), 4),
        "p95_seconds": round(_percentile(ordered, 95), 4),
        "p99_seconds": round(_percentile(ordered, 99), 4),
        "max_seconds": round(ordered[-1], 4),
        "mean_seconds": round(sum(ordered) / len(ordered), 4),
    }


# -- synthetic events ---------------------------------------------------------------------------


def _event(domain: str, n: int, at: datetime, rng: random.Random) -> LoadedEvent:
    roll = rng.random()
    outcome = "error" if roll < 0.05 else "unknown" if roll < 0.08 else "success"
    event_id = f"evt-{uuid.uuid5(uuid.NAMESPACE_URL, f'{domain}/{n}').hex}"
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": event_id,
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
    return LoadedEvent(doc_id=f"doc-{event_id}", event=TelemetryEvent.model_validate(body))


def _pointer(loaded: LoadedEvent) -> OutboxEntry:
    return OutboxEntry(
        id=loaded.doc_id,
        customer_id=CUSTOMER,
        kind="event",
        ref_id=loaded.doc_id,
        entity="event",
        event_kind="telemetry",
    )


# -- run ----------------------------------------------------------------------------------------


@dataclass
class Subscriber:
    index: int
    domain: str
    foreign: str | None
    object_id: str
    samples: list[float] = field(default_factory=list)
    foreign_deltas: int = 0
    foreign_refusals: int = 0
    other_errors: list[str] = field(default_factory=list)
    matched: int = 0
    failure: str | None = None
    ws: WebSocketTestSession | None = None


def _subscriber_loop(
    client: TestClient,
    sub: Subscriber,
    token: str,
    t0s: dict[tuple[str, int], float],
    expected: dict[str, int],
    ready: threading.Barrier,
) -> None:
    """One WebSocket session: record, per event, how long until a delta reflected it."""
    announced = False
    try:
        with client.websocket_connect(WS_URL, subprotocols=["ns.bearer", token]) as ws:
            sub.ws = ws
            ws.send_json({"type": "subscribe", "domain_id": sub.domain})
            if sub.foreign is not None:
                ws.send_json({"type": "subscribe", "domain_id": sub.foreign})
            next_unmatched = 1
            while True:
                message = ws.receive_json()
                received = time.perf_counter()  # t1
                kind = message.get("type")
                if kind == "error":
                    if sub.foreign is not None and message.get("domain_id") == sub.foreign:
                        sub.foreign_refusals += 1
                    else:
                        sub.other_errors.append(str(message.get("code")))
                    continue
                if kind != "delta":
                    continue
                if message.get("domain_id") != sub.domain:
                    sub.foreign_deltas += 1
                    continue
                frequency = (message["nodes"][0]["metrics"].get("frequency")) or 0
                if not announced:
                    announced = True
                    ready.wait(timeout=60)
                for ordinal in range(next_unmatched, min(frequency, expected[sub.domain]) + 1):
                    sub.samples.append(received - t0s[(sub.domain, ordinal)])
                    sub.matched += 1
                    next_unmatched = ordinal + 1
                if next_unmatched > expected[sub.domain]:
                    return
    except WebSocketDisconnect:
        pass  # the watchdog closed a socket that never saw its last delta
    except Exception as exc:  # recorded, then failed by the caller
        sub.failure = f"{type(exc).__name__}: {exc}"
        ready.abort()


def _real_clock_factory() -> Callable[[], float]:
    """Epoch seconds that advance in real time from the harness origin (events, buckets, scope
    ages and delta timestamps all follow it); the token validator keeps the fixed harness clock."""
    base = time.perf_counter()
    return lambda: helpers.T0 + (time.perf_counter() - base)


def _run(
    backend: str,
    label: str,
    open_store: Callable[[], Any],
    portal_factory: Callable[[], Any] = anyio.from_thread.start_blocking_portal,
) -> dict[str, Any]:
    domains = _domain_ids()
    settings = RealtimeSettings()
    clock = _real_clock_factory()
    total_events = max(1, int(EVENTS_PER_SECOND * DURATION_SECONDS))
    plan = [(domains[i % len(domains)]) for i in range(total_events)]
    expected = Counter(plan)
    subscribers = [
        Subscriber(
            index=i,
            domain=domains[i % len(domains)],
            foreign=domains[(i + 1) % len(domains)] if len(domains) > 1 else None,
            object_id=f"00000000-0000-4000-8000-{i:012d}",
        )
        for i in range(max(SUBSCRIBERS, len(domains)))
    ]
    for domain in domains:
        expected.setdefault(domain, 0)
    t0s: dict[tuple[str, int], float] = {}
    slips: list[float] = []

    with portal_factory() as portal:
        store, cleanup = portal.call(open_store)
        try:
            h = helpers.harness(
                *(
                    helpers.policy(
                        s.object_id, helpers.role(Role.VIEWER, s.domain), memberships=(s.domain,)
                    )
                    for s in subscribers
                ),
                routers={},
            )
            configure_realtime(
                h.app,
                aggregate_reader=store,
                settings=settings,
                revocation_ttl_seconds=REVOCATION_TTL_SECONDS,
                clock=clock,
            )
            client = TestClient(h.app, raise_server_exceptions=False)
            client.portal = portal  # requests and sockets run on the loop the store lives on
            events = InMemoryTraceEventSource()
            projection = AggregateProjection(
                store=store,
                ledger=None,  # type: ignore[arg-type]  # telemetry events never read the ledger
                events=events,
                clock=lambda: datetime.fromtimestamp(clock(), UTC),
            )
            ready = threading.Barrier(len(subscribers) + 1)
            threads = [
                threading.Thread(
                    target=_subscriber_loop,
                    args=(client, s, h.token(s.object_id), t0s, dict(expected), ready),
                    daemon=True,
                    name=f"subscriber-{s.index}",
                )
                for s in subscribers
            ]
            for thread in threads:
                thread.start()
            try:
                ready.wait(timeout=60)  # every subscriber holds a live, subscribed socket
            except threading.BrokenBarrierError:
                failures = [s.failure for s in subscribers if s.failure]
                pytest.fail(f"subscribers did not all connect: {failures}")

            async def write() -> None:
                rng = random.Random(7)
                seen: Counter[str] = Counter()
                started = time.perf_counter()
                for i, domain in enumerate(plan):
                    due = started + i / EVENTS_PER_SECOND
                    wait = due - time.perf_counter()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    seen[domain] += 1
                    ordinal = seen[domain]
                    loaded = _event(domain, ordinal, datetime.fromtimestamp(clock(), UTC), rng)
                    events.add(loaded)
                    entry = _pointer(loaded)
                    slips.append(max(0.0, time.perf_counter() - due))
                    t0s[(domain, ordinal)] = time.perf_counter()  # t0: handed to the rollup path
                    await projection.handle(entry)

            writing_started = time.perf_counter()
            portal.call(write)
            writing_seconds = time.perf_counter() - writing_started
            # Everything is written; allow two poll intervals plus the cache and send margins.
            deadline = time.perf_counter() + 2 * settings.poll_interval_seconds + 10.0
            for thread in threads:
                thread.join(timeout=max(0.0, deadline - time.perf_counter()))
            for thread, s in zip(threads, subscribers, strict=True):
                if thread.is_alive() and s.ws is not None:
                    s.ws.close()  # watchdog: unblocks a socket that never saw its last delta
            for thread in threads:
                thread.join(timeout=10)
        finally:
            portal.call(cleanup)

    failures = [f"subscriber {s.index}: {s.failure}" for s in subscribers if s.failure]
    samples = [x for s in subscribers for x in s.samples]
    expected_samples = sum(expected[s.domain] for s in subscribers)
    foreign_deltas = sum(s.foreign_deltas for s in subscribers)
    foreign_refusals = sum(s.foreign_refusals for s in subscribers)
    result: dict[str, Any] = {
        "label": label,
        "backend": backend,
        "definition": {
            "t0": "instant the normalized event is handed to AggregateProjection.handle "
            "(worker aggregate rollup path), time.perf_counter",
            "t1": "instant a subscribed WebSocket client receives a delta whose node frequency "
            "has reached the event's ordinal within its domain, time.perf_counter",
            "freshness": "t1 - t0 per (subscriber, event)",
        },
        "failures": failures,
        "samples": len(samples),
        "expected_samples": expected_samples,
        "target": {
            "label": TARGET_LABEL,
            "p95_seconds_at_most": TARGET_SECONDS,
            "asserted": False,
        },
        "exclusions": EXCLUSIONS,
        "disclaimer": (
            "Measured on a developer machine, one process, in-process ASGI transport and "
            "dev-issuer tokens. Not a guarantee or an SLA; G07 sized-profile evidence stays OPEN."
        ),
        "correctness": {
            "foreign_domain_deltas_received": foreign_deltas,
            "foreign_domain_subscriptions_refused": foreign_refusals,
            "foreign_attempts_expected": sum(1 for s in subscribers if s.foreign is not None),
            "unexpected_errors": sorted({e for s in subscribers for e in s.other_errors}),
            "unobserved_samples": expected_samples - len(samples),
        },
        "load": {
            "generator_max_slip_seconds": round(max(slips, default=0.0), 4),
            "generator_mean_slip_seconds": round(sum(slips) / max(1, len(slips)), 4),
            "write_phase_seconds": round(writing_seconds, 3),
            "events_total": total_events,
            "events_by_domain": {d: expected[d] for d in domains},
            "subscribers_by_domain": dict(Counter(s.domain for s in subscribers)),
        },
        "environment": {
            "python": platform.python_version(),
            "os": platform.platform(),
            "cpu_model": _cpu_model(),
            "logical_cpus": os.cpu_count(),
            "ram_gib": _ram_gib(),
            "poll_interval_seconds": settings.poll_interval_seconds,
            "source_read_cache_ttl_seconds": settings.poll_interval_seconds / 2,
            "revocation_ttl_seconds": REVOCATION_TTL_SECONDS,
            "scope_refresh_seconds": settings.scope_refresh_seconds,
            "heartbeat_seconds": settings.heartbeat_seconds,
            "knobs": {
                "NS_MAP_FRESHNESS_EVENTS_PER_SECOND": EVENTS_PER_SECOND,
                "NS_MAP_FRESHNESS_DOMAINS": len(domains),
                "NS_MAP_FRESHNESS_DURATION_SECONDS": DURATION_SECONDS,
                "NS_MAP_FRESHNESS_SUBSCRIBERS": len(subscribers),
            },
        },
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
    }
    if samples:
        result["freshness"] = _stats(samples)
        result["meets_target"] = result["freshness"]["p95_seconds"] <= TARGET_SECONDS
    return result


def _check(result: dict[str, Any]) -> None:
    assert result["failures"] == []
    correctness = result["correctness"]
    assert correctness["foreign_domain_deltas_received"] == 0, "a delta crossed a domain scope"
    assert (
        correctness["foreign_domain_subscriptions_refused"]
        == (correctness["foreign_attempts_expected"])
    ), "an out-of-scope subscription was not refused"
    assert correctness["unexpected_errors"] == []
    assert correctness["unobserved_samples"] == 0, "an event never became visible to a subscriber"
    assert result["samples"] > 0
    assert all(v >= 0 for v in (result["freshness"]["p50_seconds"],))


def _report(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fresh = result["freshness"]
    print(f"\nmap freshness ({result['label']}; backend {result['backend']})")
    print(f"  {TARGET_LABEL}; NOT asserted")
    print(
        f"  samples={result['samples']} p50={fresh['p50_seconds']:.3f}s "
        f"p95={fresh['p95_seconds']:.3f}s p99={fresh['p99_seconds']:.3f}s "
        f"max={fresh['max_seconds']:.3f}s mean={fresh['mean_seconds']:.3f}s "
        f"meets_target={result['meets_target']}"
    )
    print(f"  recorded: {path}")


def test_map_freshness_is_measured_and_recorded_in_memory() -> None:
    result = _run("InMemoryAggregateStore", LABEL_MEMORY, _open_memory)
    _check(result)
    _report(result, RESULT_DIR / "p95.json")
    assert (RESULT_DIR / "p95.json").is_file()


async def _open_memory() -> tuple[AggregateStore, Callable[[], Any]]:
    async def cleanup() -> None:
        return None

    return InMemoryAggregateStore(), cleanup


# -- compose Cosmos emulator ---------------------------------------------------------------------


@pytest.mark.integration
def test_map_freshness_is_measured_and_recorded_on_the_cosmos_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integration.ingestion.support import emulator_env  # pyright: ignore[reportMissingImports]

    for name, value in emulator_env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NS_CLOUD", raising=False)
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())

    result = _run("CosmosAggregateStore (compose vNext emulator)", LABEL_EMULATOR, _open_cosmos)
    _check(result)
    _report(result, RESULT_DIR / "p95_emulator.json")


async def _open_cosmos() -> tuple[AggregateStore, Callable[[], Any]]:
    """Open a run-unique Cosmos container on the portal's loop; unreachable is a FAILURE."""
    from azure.cosmos import PartitionKey
    from neurosphere_core.aggregates.cosmos import PARTITION_KEY_PATH, CosmosAggregateStore
    from neurosphere_core.clients import ClientLifetime, create_cosmos_client
    from neurosphere_core.cloud import Settings

    lifetime = ClientLifetime()
    database = f"it_map_fresh_{uuid.uuid4().hex[:8]}"
    holder: dict[str, Any] = {}
    try:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        holder["client"] = client
        db = await client.create_database_if_not_exists(database)
        container = await db.create_container_if_not_exists(
            id="aggregates", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
    except Exception as exc:
        await lifetime.aclose()
        pytest.fail(
            f"cosmos emulator unreachable or unusable ({type(exc).__name__}: {exc}); "
            "run: docker compose up -d --wait"
        )

    async def cleanup() -> None:
        try:
            await holder["client"].delete_database(database)
        except Exception as exc:  # best effort: the database name is run-unique
            print(f"emulator cleanup failed: {type(exc).__name__}")
        await lifetime.aclose()

    return CosmosAggregateStore(container), cleanup
