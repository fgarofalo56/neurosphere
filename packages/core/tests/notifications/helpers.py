"""Shared builders for the notification suites (self-contained: no sibling-package imports)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions.permissions import GrantTablePermissionRechecker
from neurosphere_core.admin.store import InMemoryAdminConfigRepository
from neurosphere_core.notifications import (
    ChannelRegistry,
    InMemoryOutboxStore,
    NotificationEvent,
    NotificationPublisher,
    Outbox,
    SubscriptionResolver,
)

CUSTOMER = "acme"
CLOUD = "commercial"
DOMAIN_A = "commercial:acme:core:domain:team-a"
DOMAIN_B = "commercial:acme:core:domain:team-b"
OWNER = "commercial:acme:entra:principal:p-" + "a" * 64
OTHER_OWNER = "commercial:acme:entra:principal:p-" + "b" * 64
T0 = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def channel_body(channel_id: str, domain_id: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "channel_id": channel_id,
        "cloud": CLOUD,
        "customer_id": CUSTOMER,
        "domain_id": domain_id,
        "display_name": channel_id,
        "kind": "webhook",
        "allowed_host": "localhost",
        "local_sink": True,
        "local_sink_url": "http://127.0.0.1:9000/hook",
        "enabled": enabled,
    }


def subscription_body(
    subscription_id: str,
    channel_id: str,
    domain_id: str,
    *,
    event_classes: tuple[str, ...] = ("hitl_item_assigned",),
    roles: tuple[str, ...] = ("domain_steward",),
    min_severity: str = "medium",
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "subscription_id": subscription_id,
        "cloud": CLOUD,
        "customer_id": CUSTOMER,
        "domain_id": domain_id,
        "channel_id": channel_id,
        "event_classes": list(event_classes),
        "audience_roles": list(roles),
        "min_severity": min_severity,
        "enabled": enabled,
    }


def make_event(
    domain_id: str = DOMAIN_A,
    *,
    event_class: str = "hitl_item_assigned",
    severity: str = "high",
    title: str = "Review item assigned",
    dedup_key: str = "item-1",
    window: int | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_class=event_class,
        customer_id=CUSTOMER,
        cloud=CLOUD,
        domain_id=domain_id,
        subject=TargetRef(
            canonical_id="commercial:acme:core:review_item:item-1", entity_type="review_item"
        ),
        title=title,
        severity=severity,
        link="/review/item-1",
        correlation_id="corr-1",
        dedup_key=dedup_key,
        dedup_window_seconds=window,
    )


class Rig:
    """Admin config + grants + in-memory outbox wired to a publisher."""

    def __init__(self, store: Any = None) -> None:
        self.clock = Clock()
        self.admin = InMemoryAdminConfigRepository(cloud="commercial")
        self.grants = GrantTablePermissionRechecker()
        self.store = store if store is not None else InMemoryOutboxStore()
        self.registry = ChannelRegistry(self.admin)
        self.resolver = SubscriptionResolver(self.registry, self.grants)
        self.outbox = Outbox(self.store, clock=self.clock)
        self.publisher = NotificationPublisher(self.resolver, self.outbox, self.registry)

    async def add_channel(self, channel_id: str, domain_id: str, *, enabled: bool = True) -> None:
        await self.admin.create(
            CUSTOMER,
            "notification_channel",
            channel_id,
            channel_body(channel_id, domain_id, enabled=enabled),
            updated_by=OWNER,
        )

    async def add_subscription(
        self,
        subscription_id: str,
        channel_id: str,
        domain_id: str,
        *,
        owner: str = OWNER,
        **kw: Any,
    ) -> None:
        await self.admin.create(
            CUSTOMER,
            "notification_subscription",
            subscription_id,
            subscription_body(subscription_id, channel_id, domain_id, **kw),
            updated_by=owner,
        )
