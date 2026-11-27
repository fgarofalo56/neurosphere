"""Notification delivery worker over a REAL local HTTP receiver (PRP-107 item 5).

The worker runs with the real ``EgressGuard`` and ``WebhookSender`` through a local-sink channel
(``ns_env=local``) against a stdlib server on 127.0.0.1. The outbox is the in-memory twin; admin
config, grants and audit are the in-memory doubles. Time is a controllable clock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

import pytest
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_core.actions.permissions import GrantTablePermissionRechecker
from neurosphere_core.admin.store import InMemoryAdminConfigRepository
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.store import InMemoryAuditStore
from neurosphere_core.notifications import (
    ChannelRegistry,
    InMemoryOutboxStore,
    NotificationDelivery,
    NotificationEvent,
    NotificationPublisher,
    Outbox,
    OutboxEntry,
    SubscriptionResolver,
)
from neurosphere_core.notifications.egress import EgressGuard
from neurosphere_workers.notifications.worker import NotificationDeliveryWorker
from opentelemetry.metrics import Meter
from pydantic import SecretStr

CUSTOMER = "acme"
CLOUD = "commercial"
DOMAIN_A = "commercial:acme:core:domain:team-a"
DOMAIN_B = "commercial:acme:core:domain:team-b"
OWNER = "commercial:acme:entra:principal:p-" + "a" * 64
T0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
HMAC_KEY = "hm" + "ac-key-" + "q4" * 8
HMAC_REF = "https://vault-a.vault.azure.net/secrets/hmac-key"
OTHER_TITLE = "Quarterly-bonus-for-team-b"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Receiver:
    """Real HTTP server on loopback; answers from a script, then ``default``."""

    def __init__(self) -> None:
        self.requests: list[bytes] = []
        self.script: list[int] = []
        self.default = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                receiver.requests.append(self.rfile.read(length))
                status = receiver.script.pop(0) if receiver.script else receiver.default
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Receiver:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    with Receiver() as r:
        yield r


class Secrets:
    async def read(self, reference: CredentialReference) -> SecretStr:
        return SecretStr(HMAC_KEY)


@dataclass
class FakeCounter:
    name: str
    calls: list[tuple[int, dict[str, str]]] = field(default_factory=list)

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        self.calls.append((amount, dict(attributes or {})))


class FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, FakeCounter] = {}

    def create_counter(self, name: str, **_: Any) -> FakeCounter:
        return self.counters.setdefault(name, FakeCounter(name))


class SnapshotDueStore:
    """A second worker's view: ``due`` answers a stale snapshot, everything else is shared."""

    def __init__(self, shared: InMemoryOutboxStore, snapshot: list[OutboxEntry]) -> None:
        self._shared = shared
        self._snapshot = snapshot

    async def due(self, **_: Any) -> list[OutboxEntry]:
        return list(self._snapshot)

    async def create_if_absent(self, delivery: NotificationDelivery) -> Any:
        return await self._shared.create_if_absent(delivery)

    async def get(self, customer_id: str, notification_id: str) -> OutboxEntry | None:
        return await self._shared.get(customer_id, notification_id)

    async def find_by_dedup(self, *args: Any, **kw: Any) -> OutboxEntry | None:
        return await self._shared.find_by_dedup(*args, **kw)

    async def list_deliveries(self, *args: Any, **kw: Any) -> list[OutboxEntry]:
        return await self._shared.list_deliveries(*args, **kw)

    async def replace(self, entry: OutboxEntry, delivery: NotificationDelivery) -> OutboxEntry:
        return await self._shared.replace(entry, delivery)


def make_event(
    domain_id: str = DOMAIN_A,
    *,
    title: str = "Review item assigned",
    dedup_key: str = "item-1",
) -> NotificationEvent:
    return NotificationEvent(
        event_class="hitl_item_assigned",
        customer_id=CUSTOMER,
        cloud=CLOUD,
        domain_id=domain_id,
        subject=TargetRef(
            canonical_id="commercial:acme:core:review_item:item-1", entity_type="review_item"
        ),
        title=title,
        severity="high",
        link="/review/item-1",
        correlation_id="corr-1",
        dedup_key=dedup_key,
    )


class Rig:
    def __init__(self, url: str, *, max_attempts: int = 8, with_setting: bool = True) -> None:
        self.url = url
        self.clock = Clock()
        self.admin = InMemoryAdminConfigRepository(cloud="commercial")
        self.grants = GrantTablePermissionRechecker()
        self.store = InMemoryOutboxStore()
        self.registry = ChannelRegistry(self.admin)
        self.resolver = SubscriptionResolver(self.registry, self.grants)
        self.outbox = Outbox(self.store, clock=self.clock)
        self.publisher = NotificationPublisher(self.resolver, self.outbox, self.registry)
        self.audit_store = InMemoryAuditStore()
        self.audit = AuditRepository(self.audit_store, clock=self.clock)
        self.meter = FakeMeter()
        self.max_attempts = max_attempts
        self.with_setting = with_setting

    async def setup(self, *, domains: tuple[str, ...] = (DOMAIN_A,)) -> None:
        if self.with_setting:
            await self.admin.create(
                CUSTOMER,
                "system_setting",
                "notifications",
                {
                    "schema_version": "1.0.0",
                    "setting_key": "notifications",
                    "enabled": True,
                    "notifications": {
                        "egress_allowed_hosts": ["localhost"],
                        "max_attempts": self.max_attempts,
                        "retry_base_seconds": 30,
                        "dedup_window_seconds": 900,
                    },
                },
                updated_by=OWNER,
            )
        for domain in domains:
            slug = domain.rsplit(":", 1)[1]
            await self.admin.create(
                CUSTOMER,
                "notification_channel",
                f"hook-{slug}",
                {
                    "schema_version": "1.0.0",
                    "channel_id": f"hook-{slug}",
                    "cloud": CLOUD,
                    "customer_id": CUSTOMER,
                    "domain_id": domain,
                    "display_name": f"hook {slug}",
                    "kind": "webhook",
                    "allowed_host": "localhost",
                    "hmac_credential": {"kind": "key_vault_secret", "secret_uri": HMAC_REF},
                    "local_sink": True,
                    "local_sink_url": self.url,
                    "enabled": True,
                },
                updated_by=OWNER,
            )
            await self.admin.create(
                CUSTOMER,
                "notification_subscription",
                f"sub-{slug}",
                {
                    "schema_version": "1.0.0",
                    "subscription_id": f"sub-{slug}",
                    "cloud": CLOUD,
                    "customer_id": CUSTOMER,
                    "domain_id": domain,
                    "channel_id": f"hook-{slug}",
                    "event_classes": ["hitl_item_assigned"],
                    "audience_roles": ["domain_steward"],
                    "min_severity": "medium",
                    "enabled": True,
                },
                updated_by=OWNER,
            )
            self.grants.grant(OWNER, CUSTOMER, domain, "data.read")

    def worker(self, store: Any = None) -> NotificationDeliveryWorker:
        outbox = Outbox(store, clock=self.clock) if store is not None else self.outbox
        return NotificationDeliveryWorker(
            outbox=outbox,
            registry=self.registry,
            resolver=self.resolver,
            secrets=Secrets(),
            guard=EgressGuard(),
            audit=self.audit,
            customer_id=CUSTOMER,
            ns_env="local",
            deployment_cloud=CLOUD,
            clock=self.clock,
            meter=cast(Meter, self.meter),
        )

    async def row(self, notification_id: str) -> NotificationDelivery:
        entry = await self.store.get(CUSTOMER, notification_id)
        assert entry is not None
        return entry.delivery

    async def audit_records(self, domain: str = DOMAIN_A) -> list[Any]:
        return await self.audit.read_range(domain_audit_chain_id(CUSTOMER, domain))

    def count(self, name: str) -> int:
        counter = self.meter.counters.get(name)
        return sum(n for n, _ in counter.calls) if counter else 0


def code(row: NotificationDelivery) -> str | None:
    return row.last_error_code.root if row.last_error_code is not None else None


async def published(rig: Rig, event: NotificationEvent | None = None) -> str:
    created = await rig.publisher.publish(event or make_event())
    assert len(created) == 1
    return created[0].notification_id.root


# 1 -------------------------------------------------------------------------------------------


async def test_500_then_200_is_two_posts_one_delivery_and_backoff_is_respected(
    receiver: Receiver,
) -> None:
    receiver.script = [500]
    rig = Rig(receiver.url)
    await rig.setup()
    nid = await published(rig)
    worker = rig.worker()

    report = await worker.tick()
    assert report.retried == 1
    assert len(receiver.requests) == 1
    row = await rig.row(nid)
    assert row.status == "pending" and code(row) == "http_status"

    await worker.tick()  # same instant: next_attempt_at is in the future
    rig.clock.advance(29)
    await worker.tick()
    assert len(receiver.requests) == 1

    rig.clock.advance(1)  # 30 s base backoff reached
    report = await worker.tick()
    assert report.delivered == 1
    assert len(receiver.requests) == 2
    assert (await rig.row(nid)).status == "delivered"

    rig.clock.advance(10_000)
    await worker.tick()
    assert len(receiver.requests) == 2
    assert rig.count("ns.notifications.delivered") == 1
    assert await rig.audit_records() == []


# 2 -------------------------------------------------------------------------------------------


async def test_permanent_500_fails_after_max_attempts_with_counter_and_one_audit_record(
    receiver: Receiver,
) -> None:
    receiver.default = 500
    rig = Rig(receiver.url, max_attempts=3)
    await rig.setup()
    nid = await published(rig)
    worker = rig.worker()

    for _ in range(6):
        await worker.tick()
        rig.clock.advance(1000)

    row = await rig.row(nid)
    assert row.status == "failed" and row.attempts == 3
    assert code(row) == "http_status"
    assert len(receiver.requests) == 3

    failed = rig.meter.counters["ns.notifications.failed"].calls
    assert failed == [
        (
            1,
            {
                "event_class": "hitl_item_assigned",
                "channel_kind": "webhook",
                "reason": "http_status",
            },
        )
    ]
    records = await rig.audit_records()
    assert len(records) == 1
    assert records[0].operation == "notification.delivery"
    text = json.dumps(records[0].model_dump(mode="json"))
    assert "hook-team-a" in text and nid in text and "http_status" in text
    for banned in (receiver.url, "127.0.0.1", "/hook", "localhost", HMAC_KEY, HMAC_REF, "?"):
        assert banned not in text


# 3 -------------------------------------------------------------------------------------------


async def test_same_event_published_twice_posts_once(receiver: Receiver) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    assert len(await rig.publisher.publish(make_event())) == 1
    assert await rig.publisher.publish(make_event()) == []
    worker = rig.worker()
    await worker.tick()
    await worker.tick()
    rig.clock.advance(5000)
    await worker.tick()
    assert len(receiver.requests) == 1


# 4 -------------------------------------------------------------------------------------------


async def test_owner_losing_data_read_before_delivery_suppresses_without_a_request(
    receiver: Receiver,
) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    nid = await published(rig)
    rig.grants.revoke(OWNER, CUSTOMER, DOMAIN_A, "data.read")

    report = await rig.worker().tick()
    assert report.suppressed == 1
    assert receiver.requests == []
    row = await rig.row(nid)
    assert row.status == "suppressed" and code(row) == "scope"
    assert rig.count("ns.notifications.suppressed") == 1


async def test_other_domains_event_never_reaches_a_channel_scoped_elsewhere(
    receiver: Receiver,
) -> None:
    rig = Rig(receiver.url)
    await rig.setup()  # subscription and channel exist for DOMAIN_A only
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_B, "data.read")
    assert await rig.publisher.publish(make_event(DOMAIN_B, title=OTHER_TITLE)) == []
    await published(rig, make_event(DOMAIN_A, title="Team A item", dedup_key="item-2"))

    worker = rig.worker()
    await worker.tick()
    assert len(receiver.requests) == 1
    body = receiver.requests[0].decode("utf-8")
    assert DOMAIN_B not in body and OTHER_TITLE not in body and "team-b" not in body
    assert len(await rig.store.list_deliveries(CUSTOMER)) == 1


async def test_recheck_outage_retries_without_sending_or_dropping(receiver: Receiver) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    nid = await published(rig)
    rig.grants.fail_with(RuntimeError("policy store down"))
    worker = rig.worker()

    report = await worker.tick()
    assert report.retried == 1 and receiver.requests == []
    row = await rig.row(nid)
    assert row.status == "pending" and code(row) == "scope_recheck_unavailable"

    rig.grants.fail_with(None)
    rig.clock.advance(30)
    await worker.tick()
    assert (await rig.row(nid)).status == "delivered"
    assert len(receiver.requests) == 1


async def test_missing_setting_skips_the_tick_and_leaves_rows_pending(receiver: Receiver) -> None:
    rig = Rig(receiver.url, with_setting=False)
    await rig.setup()
    nid = await published(rig)

    report = await rig.worker().tick()
    assert report.skipped == "notifications_setting_missing"
    assert receiver.requests == []
    assert (await rig.row(nid)).status == "pending"
    assert rig.meter.counters["ns.notifications.tick_skipped"].calls == [
        (1, {"reason": "notifications_setting_missing"})
    ]


# 5 -------------------------------------------------------------------------------------------


async def test_two_workers_over_the_same_store_send_once(receiver: Receiver) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    await published(rig)
    snapshot = await rig.store.due(now=rig.clock(), limit=10, customer_id=CUSTOMER)
    assert len(snapshot) == 1
    first = rig.worker()
    second = rig.worker(SnapshotDueStore(rig.store, snapshot))

    reports = await asyncio.gather(first.tick(), second.tick())

    assert len(receiver.requests) == 1
    assert sorted(r.delivered for r in reports) == [0, 1]
    assert sorted(r.conflicts for r in reports) == [0, 1]


async def test_worker_that_died_after_claim_is_reclaimed_after_the_lease(
    receiver: Receiver,
) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    nid = await published(rig)
    entry = (await rig.store.due(now=rig.clock(), limit=10, customer_id=CUSTOMER))[0]
    assert await rig.outbox.claim(entry) is not None  # ... and the worker process died here
    assert (await rig.row(nid)).status == "sending"

    worker = rig.worker()
    await worker.tick()
    rig.clock.advance(299)
    await worker.tick()
    assert receiver.requests == []  # lease still held

    rig.clock.advance(2)
    await worker.tick()
    assert len(receiver.requests) == 1
    row = await rig.row(nid)
    assert row.status == "delivered" and row.attempts == 2
    rig.clock.advance(10_000)
    await worker.tick()
    assert len(receiver.requests) == 1


# 6 -------------------------------------------------------------------------------------------


async def test_no_log_line_carries_url_secret_or_other_domain_title(
    receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    receiver.script = [500, 500, 500]
    rig = Rig(receiver.url, max_attempts=3)
    await rig.setup()
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_B, "data.read")
    await rig.publisher.publish(make_event(DOMAIN_B, title=OTHER_TITLE))
    await published(rig, make_event(DOMAIN_A, title="Team A item", dedup_key="item-2"))
    worker = rig.worker()

    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            await worker.tick()
            rig.clock.advance(1000)
        rig.grants.fail_with(RuntimeError(f"down {receiver.url} {HMAC_KEY}"))
        await worker.tick()

    assert caplog.records
    text = "\n".join(
        record.getMessage() + " " + json.dumps(record.__dict__, default=str)
        for record in caplog.records
    )
    for banned in (receiver.url, "/hook", HMAC_KEY, HMAC_REF, OTHER_TITLE, "Team A item"):
        assert banned not in text


async def test_channel_kind_without_a_sender_fails_without_retry(receiver: Receiver) -> None:
    rig = Rig(receiver.url)
    await rig.setup()
    nid = await published(rig)
    # The channel is rewritten as an e-mail channel (no transport is built): permanent failure.
    doc = await rig.admin.get(CUSTOMER, "notification_channel", "hook-team-a")
    assert doc is not None
    body = doc.body.model_dump(mode="json")
    body.update(
        {
            "kind": "email",
            "allowed_host": "smtp.example.com",
            "local_sink": False,
            "local_sink_url": None,
            "hmac_credential": None,
            "endpoint_credential": {"kind": "key_vault_secret", "secret_uri": HMAC_REF},
        }
    )
    await rig.admin.replace(
        CUSTOMER,
        "notification_channel",
        "hook-team-a",
        body,
        if_match=doc.etag.root,
        updated_by=OWNER,
    )

    await rig.worker().tick()
    row = await rig.row(nid)
    assert row.status == "failed" and row.attempts == 1
    assert receiver.requests == []
    assert len(await rig.audit_records()) == 1
