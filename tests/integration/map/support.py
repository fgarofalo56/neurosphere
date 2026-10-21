"""The in-process composition root for PRP-18: what a deployment's startup code will do.

Nothing in production wires authz, aggregates and the catalog together yet (``main.py`` only does
ingest and scan; tests compose), so this module IS the composition root under test. It builds the
default app with ``create_app`` (the ``REGISTERED`` hooks, no test-supplied routers), configures
the map, replay and realtime collaborators through their documented ``app.state`` seams, and
registers the gateway with the revocation fan-out.

All data is synthetic and in memory except the aggregate store, which the caller chooses (the
unmarked test passes the in-memory store, the integration-marked test a Cosmos emulator store).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import map_api_helpers as map_helpers  # pyright: ignore[reportMissingImports]
import replay_support  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient
from neurosphere_api.map import PREFIX as MAP_PREFIX
from neurosphere_api.map import get_clock
from neurosphere_api.realtime import PREFIX as REALTIME_PREFIX
from neurosphere_api.realtime import GatewayRegistry, RealtimeSettings, configure_realtime
from neurosphere_api.replay import PREFIX as REPLAY_PREFIX
from neurosphere_api.replay import InMemoryTraceReader
from neurosphere_core.aggregates import (
    AggregateStatus,
    AggregateStore,
    ErrorPoint,
    LatencyPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
    format_fine,
)
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationAuditEvent,
    RevocationHookRegistry,
    RevocationOutcome,
    RevocationService,
    ScopePermissionRevocationAuthorizer,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

ALICE: str = helpers.ALICE  # reads FINANCE
BOB: str = helpers.BOB  # reads OPERATIONS only
ADMIN: str = helpers.CAROL  # Admin on FINANCE: may revoke
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
CUSTOMER: str = helpers.CUSTOMER
TTL = 10.0
WS_URL = f"{REALTIME_PREFIX}/ws"
VIEWPORT = f"{MAP_PREFIX}/domains/{{domain}}/viewport"
TRACES = f"{REPLAY_PREFIX}/domains/{{domain}}/traces"
P95_MS = 120
REQUESTS = 40


class _Auditor:
    """Collects revocation audit events (metadata only), as the real auditor would persist."""

    def __init__(self) -> None:
        self.events: list[RevocationAuditEvent] = []

    async def record(self, event: RevocationAuditEvent) -> None:
        self.events.append(event)


async def seed_aggregates(store: AggregateStore, *domains: str, lag_seconds: float = 1.0) -> None:
    """One latency + errors hour bucket per domain and the customer watermark, relative to the
    harness clock origin ``T0``. Async so a Cosmos store stays on the event loop that opened it."""
    moment = datetime.fromtimestamp(helpers.T0, UTC)
    start = format_bucket(bucket_start(moment, "hour"))
    for domain in domains:

        def base(metric: str, domain: str = domain) -> dict[str, Any]:
            return {
                "id": aggregate_doc_id(CUSTOMER, domain, metric, "hour", start, metric),
                "customer_id": CUSTOMER,
                "domain_id": domain,
                "grain": "hour",
                "bucket_start": start,
                "series_key": metric,
                "watermark": start,
                "complete": True,
            }

        docs = [
            LatencyPoint(
                **base("latency"),
                sample_count=REQUESTS,
                missing_count=0,
                p50_ms=50,
                p95_ms=P95_MS,
            ),
            ErrorPoint(
                **base("errors"),
                request_count=REQUESTS,
                unknown_count=0,
                error_count=2,
                error_rate=2 / REQUESTS,
            ),
        ]
        await store.replace_bucket(CUSTOMER, domain, "hour", start, docs)
    watermark = datetime.fromtimestamp(helpers.T0 - lag_seconds, UTC)
    await store.put_status(AggregateStatus(customer_id=CUSTOMER, watermark=format_fine(watermark)))


@dataclass
class Wiring:
    """The composed app plus the handles a test needs."""

    h: Any
    api: Any
    hooks: RevocationHookRegistry
    service: RevocationService
    registry: GatewayRegistry
    auditor: _Auditor
    traces: InMemoryTraceReader
    clients: list[TestClient] = field(default_factory=list)

    def client(self) -> TestClient:
        client = TestClient(self.h.app, raise_server_exceptions=False)
        self.clients.append(client)
        return client

    def connect(self, client: TestClient, object_id: str) -> Any:
        token = self.h.token(object_id)
        return client.websocket_connect(WS_URL, subprotocols=["ns.bearer", token])

    async def revoke(self, object_id: str) -> RevocationOutcome:
        """Revoke ``object_id`` as the Admin, through the real service and the registered hooks."""
        claims = await self.h.validator.authenticate(self.h.auth(ADMIN)["Authorization"])
        actor = (await self.h.deriver.derive(claims)).scope
        return await self.service.revoke(
            actor, helpers.principal_id_for(object_id), reason="security_incident"
        )


def compose(store: AggregateStore) -> Wiring:
    """Build the app as startup code would, over ``store`` as the hot aggregate store."""
    holder: dict[str, Any] = {}
    revocations = InMemoryRevocationStore(clock=lambda: holder["h"].clock.now)
    checker = CachedRevocationChecker(
        revocations, ttl_seconds=TTL, clock=lambda: holder["h"].clock.now
    )
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
        helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(
            map_helpers.STEWARD_BOTH, helpers.role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)
        ),
        routers={},  # the default hooks only: this fails if a REGISTERED hook is dropped
        revocation_checker=checker,
    )
    holder["h"] = h
    app = h.app

    # map: catalog repository + graph, aggregate reader, pseudonymizer
    repo = InMemoryCatalogRepository()
    app.state.catalog_repository = repo
    app.state.aggregate_reader = store
    app.state.map_pseudonymizer = helpers.pseudonymizer()
    app.dependency_overrides[get_clock] = lambda: lambda: map_helpers.NOW
    api = map_helpers.Api(h=h, repo=repo, store=store)  # type: ignore[arg-type]
    api.seed(map_helpers.agent_doc("wired", FINANCE))

    # replay: stored, redacted spans
    traces = InMemoryTraceReader()
    traces.add(
        replay_support.span(1, None),
        replay_support.span(2, 1, offset_ms=10, kind="model_call"),
    )
    app.state.trace_reader = traces

    # realtime: the gateway on the same aggregates; its registry joins the revocation fan-out
    registry = configure_realtime(
        app,
        aggregate_reader=store,
        settings=RealtimeSettings(poll_interval_seconds=30.0),
        revocation_ttl_seconds=TTL,
        clock=h.clock,
    )
    hooks = RevocationHookRegistry()
    hooks.register_push_registry("websocket", registry)
    hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    hooks.register_cache_invalidator("scope-deriver", h.deriver.invalidate_principal)
    auditor = _Auditor()
    service = RevocationService(
        store=revocations,
        authorizer=ScopePermissionRevocationAuthorizer(clock=h.clock),
        auditor=auditor,
        hooks=hooks,
        ttl_seconds=TTL,
        clock=h.clock,
    )
    return Wiring(
        h=h,
        api=api,
        hooks=hooks,
        service=service,
        registry=registry,
        auditor=auditor,
        traces=traces,
    )


# -- websocket helpers (tolerant of message types this suite does not assert on) ------------------


def next_of_type(ws: WebSocketTestSession, kind: str, *, limit: int = 20) -> dict[str, Any]:
    """The next message of ``kind``; ``subscribed``, ``pong``, errors etc. are skipped."""
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == kind:
            return message
    raise AssertionError(f"no {kind!r} message within {limit} messages")


def until_pong(ws: WebSocketTestSession, *, limit: int = 50) -> list[dict[str, Any]]:
    """Send a ping and return every message that arrived before the pong."""
    ws.send_json({"type": "ping"})
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == "pong":
            return seen
        seen.append(message)
    raise AssertionError("no pong")


def drain(ws: WebSocketTestSession, *, limit: int = 50) -> tuple[list[dict[str, Any]], int | None]:
    """Messages until the server closes; returns (messages, close code)."""
    messages: list[dict[str, Any]] = []
    for _ in range(limit):
        try:
            messages.append(ws.receive_json())
        except WebSocketDisconnect as exc:
            return messages, exc.code
    raise AssertionError("server did not close the socket")
