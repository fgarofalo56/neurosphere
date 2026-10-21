"""Harness for the realtime gateway tests (PRP-18 item 1).

Reuses the PRP-06 authz harness (dev-issuer tokens, in-memory policy, fake clock) and adds an
in-memory aggregate store, a revocation checker on the same fake clock, and a GATED sleeper:
the gateway's pump loop waits for :meth:`Rig.tick`, so each poll cycle is driven by the test and
nothing sleeps for real. ``tick`` returns only after the pump finished the cycle and is waiting
again, which makes "no message was pushed" assertions deterministic.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    T0,
    FakeClock,
    Harness,
    at,
    harness,
    principal_id_for,
)
from fastapi.testclient import TestClient
from neurosphere_api.realtime import GatewayRegistry, RealtimeSettings, configure_realtime
from neurosphere_api.realtime.router import PREFIX, build_router
from neurosphere_core.aggregates import (
    AggregateStatus,
    ErrorPoint,
    InMemoryAggregateStore,
    LatencyPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
    format_fine,
)
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationEntry,
)
from neurosphere_core.auth.scope import PrincipalPolicy
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

WS_URL = f"{PREFIX}/ws"
TTL = 10.0
POLL = 2.0


class Ticker:
    """Gated sleeper plus the fake-clock advance for one poll interval."""

    def __init__(self, clock: FakeClock, interval: float = POLL) -> None:
        self._clock = clock
        self._interval = interval
        self._gate = asyncio.Semaphore(0)
        self.calls = 0

    async def sleeper(self, seconds: float) -> None:
        self.calls += 1
        await self._gate.acquire()

    async def tick(self, pumps: int = 1, abort: Callable[[], bool] | None = None) -> None:
        """Run one poll cycle; ``abort`` ends the wait early (the cycle closed the session)."""
        for _ in range(2000):
            if self.calls >= pumps:
                break
            await asyncio.sleep(0.001)
        before = self.calls
        self._clock.advance(self._interval)
        for _ in range(pumps):
            self._gate.release()
        for _ in range(5000):
            if self.calls >= before + pumps or (abort is not None and abort()):
                return
            await asyncio.sleep(0.001)
        raise AssertionError("pump did not complete a cycle")


@dataclass
class Rig:
    h: Harness
    revocations: InMemoryRevocationStore
    aggregates: InMemoryAggregateStore
    registry: GatewayRegistry
    ticker: Ticker
    settings: RealtimeSettings
    clients: list[TestClient] = field(default_factory=list)

    def client(self) -> TestClient:
        client = TestClient(self.h.app, raise_server_exceptions=False)
        self.clients.append(client)
        return client

    async def _tick(self) -> None:
        open_now = self.registry.session_count
        await self.ticker.tick(abort=lambda: self.registry.session_count < open_now)

    def tick(self, client: TestClient, count: int = 1) -> None:
        for _ in range(count):
            assert client.portal is not None
            client.portal.call(self._tick)

    def tick_until_closed(self, client: TestClient, max_ticks: int = 100) -> int:
        """Tick until no session is open; returns the number of ticks it took."""
        for n in range(1, max_ticks + 1):
            self.tick(client)
            if self.registry.session_count == 0:
                return n
        raise AssertionError("session still open")

    def connect(self, client: TestClient, object_id: str) -> Any:
        token = self.h.token(object_id)
        return client.websocket_connect(WS_URL, subprotocols=["ns.bearer", token])


def build_rig(*policies: PrincipalPolicy, **settings: Any) -> Rig:
    holder: dict[str, Harness] = {}
    revocations = InMemoryRevocationStore(clock=lambda: holder["h"].clock.now)
    checker = CachedRevocationChecker(
        revocations, ttl_seconds=TTL, clock=lambda: holder["h"].clock.now
    )
    h = harness(
        *policies,
        routers={PREFIX: build_router()},
        revocation_checker=checker,
    )
    holder["h"] = h
    aggregates = InMemoryAggregateStore()
    cfg = RealtimeSettings(poll_interval_seconds=POLL, **settings)
    ticker = Ticker(h.clock)
    registry = configure_realtime(
        h.app,
        aggregate_reader=aggregates,
        settings=cfg,
        revocation_ttl_seconds=TTL,
        clock=h.clock,
        sleeper=ticker.sleeper,
    )
    return Rig(
        h=h,
        revocations=revocations,
        aggregates=aggregates,
        registry=registry,
        ticker=ticker,
        settings=cfg,
    )


def revoke(rig: Rig, object_id: str, *, at_offset: float = 0.0) -> None:
    """Record a revocation in the store only (what ANOTHER replica would do: no fan-out here)."""
    pid = principal_id_for(object_id)
    entry = RevocationEntry(
        principal_id=pid, revoked_at=at(at_offset), reason="security_incident", revoked_by=pid
    )
    asyncio.run(rig.revocations.put(entry))


def seed_domain(
    store: InMemoryAggregateStore,
    domain_id: str,
    *,
    p95_ms: int | None = 120,
    requests: int = 40,
    errors: int = 2,
    lag_seconds: float | None = 1.0,
) -> None:
    """Write one hour bucket (latency + errors) and the customer status, relative to ``T0``."""
    moment = datetime.fromtimestamp(T0, UTC)
    start = format_bucket(bucket_start(moment, "hour"))

    def base(metric: str) -> dict[str, Any]:
        return {
            "id": aggregate_doc_id(CUSTOMER, domain_id, metric, "hour", start, metric),
            "customer_id": CUSTOMER,
            "domain_id": domain_id,
            "grain": "hour",
            "bucket_start": start,
            "series_key": metric,
            "watermark": start,
            "complete": True,
        }

    docs = [
        LatencyPoint(
            **base("latency"), sample_count=requests, missing_count=0, p50_ms=50, p95_ms=p95_ms
        ),
        ErrorPoint(
            **base("errors"),
            request_count=requests,
            unknown_count=0,
            error_count=errors,
            error_rate=errors / requests,
        ),
    ]
    asyncio.run(store.replace_bucket(CUSTOMER, domain_id, "hour", start, docs))
    if lag_seconds is not None:
        watermark = datetime.fromtimestamp(T0 - lag_seconds, UTC)
        status = AggregateStatus(customer_id=CUSTOMER, watermark=format_fine(watermark))
        asyncio.run(store.put_status(status))


def drain(ws: WebSocketTestSession, *, limit: int = 50) -> tuple[list[dict[str, Any]], int | None]:
    """Messages until the server closes; returns (messages, close code)."""
    messages: list[dict[str, Any]] = []
    for _ in range(limit):
        try:
            messages.append(ws.receive_json())
        except WebSocketDisconnect as exc:
            return messages, exc.code
    raise AssertionError("server did not close the socket")


def until_pong(ws: WebSocketTestSession, *, limit: int = 50) -> list[dict[str, Any]]:
    """Send a ping and return every message that arrived before the pong."""
    ws.send_json({"type": "ping"})
    messages: list[dict[str, Any]] = []
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == "pong":
            return messages
        messages.append(message)
    raise AssertionError("no pong")
