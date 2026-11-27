"""PRP-107 item 6: a ``policy_eval`` tick that opens a violation queues one outbox row."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from neurosphere_core.actions.permissions import GrantTablePermissionRechecker
from neurosphere_core.admin.store import InMemoryAdminConfigRepository
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.governance.policy import NoopViolationEventSink, ViolationEvent
from neurosphere_core.notifications import (
    ChannelRegistry,
    InMemoryOutboxStore,
    NotificationPublisher,
    Outbox,
    SubscriptionResolver,
)
from neurosphere_core.notifications.violations import ViolationNotificationSink
from neurosphere_workers.notifications import wiring as notification_wiring
from neurosphere_workers.policy_eval import assembly
from neurosphere_workers.policy_eval.assembly import violation_event_sink
from neurosphere_workers.runtime.factories import RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from . import support
from .support import CUSTOMER, DOMAIN_A, build_harness, pii_policy

OWNER = f"commercial:{CUSTOMER}:entra:principal:p-" + "a" * 64


class Rig:
    def __init__(self) -> None:
        self.admin = InMemoryAdminConfigRepository(cloud="commercial")
        self.grants = GrantTablePermissionRechecker()
        self.store = InMemoryOutboxStore()
        registry = ChannelRegistry(self.admin)
        self.publisher = NotificationPublisher(
            SubscriptionResolver(registry, self.grants), Outbox(self.store), registry
        )

    async def subscribe(self, *classes: str) -> None:
        channel: dict[str, Any] = {
            "schema_version": "1.0.0",
            "channel_id": "ch-1",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": DOMAIN_A,
            "display_name": "ch-1",
            "kind": "webhook",
            "allowed_host": "localhost",
            "local_sink": True,
            "local_sink_url": "http://127.0.0.1:9000/hook",
            "enabled": True,
        }
        sub: dict[str, Any] = {
            "schema_version": "1.0.0",
            "subscription_id": "sub-1",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": DOMAIN_A,
            "channel_id": "ch-1",
            "event_classes": list(classes),
            "audience_roles": ["domain_steward"],
            "min_severity": "low",
            "enabled": True,
        }
        await self.admin.create(CUSTOMER, "notification_channel", "ch-1", channel, updated_by=OWNER)
        await self.admin.create(
            CUSTOMER, "notification_subscription", "sub-1", sub, updated_by=OWNER
        )
        self.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")

    async def rows(self) -> list[Any]:
        return [e.delivery for e in await self.store.list_deliveries(CUSTOMER)]


async def test_a_tick_that_opens_a_violation_queues_one_pending_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    await rig.subscribe("policy_violation_opened")
    sink = ViolationNotificationSink(rig.publisher)
    monkeypatch.setattr(support, "NoopViolationEventSink", lambda: sink)
    harness = await build_harness()
    await harness.publish(pii_policy())

    first = await harness.parts.worker.tick()
    assert first.run is not None
    assert len(first.run.opened_violation_ids) == 1
    rows = await rig.rows()
    assert [(r.event_class.root, r.status) for r in rows] == [
        ("policy_violation_opened", "pending")
    ]
    row = rows[0]
    assert row.subject.entity_type == "policy_violation"
    assert first.run.opened_violation_ids[0] in row.link
    assert "Source customers" not in row.title

    # The next interval observes the same open violation: nothing new is queued.
    harness.clock.advance(minutes=6)
    harness.monotonic.advance(301)
    second = await harness.parts.worker.tick()
    assert second.run is not None
    assert second.run.opened_violation_ids == ()
    assert len(await rig.rows()) == 1


def _event(violation_id: str = "v-1") -> ViolationEvent:
    return ViolationEvent(
        event_class="policy_violation_opened",
        cloud="commercial",
        customer_id=CUSTOMER,
        domain_id=DOMAIN_A,
        violation_id=violation_id,
        policy_id="pii-guard",
        policy_version=1,
        rule_id="pii-read",
        subject_id=f"commercial:{CUSTOMER}:foundry:agent:reader",
        severity="high",
        correlation_id="corr-1",
    )


async def test_the_same_event_published_twice_queues_once() -> None:
    rig = Rig()
    await rig.subscribe("policy_violation_opened")
    sink = ViolationNotificationSink(rig.publisher)
    await sink.opened(_event())
    await sink.opened(_event())
    await sink.opened(_event("v-2"))
    assert len(await rig.rows()) == 2


async def test_a_class_nobody_subscribed_to_queues_nothing() -> None:
    rig = Rig()
    await rig.subscribe("policy_violation_resolved")
    await ViolationNotificationSink(rig.publisher).opened(_event())
    assert await rig.rows() == []


class _Exploding:
    async def publish(self, event: Any) -> list[Any]:
        raise RuntimeError("outbox store down")


async def test_a_raising_publisher_does_not_raise_from_the_sink() -> None:
    await ViolationNotificationSink(_Exploding()).opened(_event())  # type: ignore[arg-type]


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(
            tenant_id="11111111-2222-4333-8444-555555555555",
            object_id="66666666-7777-4888-9999-aaaaaaaaaaaa",
        ),  # type: ignore[call-arg]
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


async def test_binding_returns_the_noop_sink_when_notifications_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NS_COSMOS_KEY", raising=False)
    async with ClientLifetime() as lifetime:
        assert isinstance(violation_event_sink(_config(), lifetime), NoopViolationEventSink)


async def test_binding_returns_the_notification_sink_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_COSMOS_KEY", "emulator-placeholder")
    monkeypatch.setattr(assembly, "create_cosmos_client", lambda *a, **k: MagicMock())
    rig = Rig()
    monkeypatch.setattr(notification_wiring, "build_publisher", lambda cfg, client: rig.publisher)
    async with ClientLifetime() as lifetime:
        sink = violation_event_sink(_config(), lifetime)
    assert isinstance(sink, ViolationNotificationSink)


async def test_binding_falls_back_to_noop_when_no_publisher_can_be_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_COSMOS_KEY", "emulator-placeholder")
    monkeypatch.setattr(assembly, "create_cosmos_client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(notification_wiring, "build_publisher", lambda cfg, client: None)
    async with ClientLifetime() as lifetime:
        assert isinstance(violation_event_sink(_config(), lifetime), NoopViolationEventSink)
