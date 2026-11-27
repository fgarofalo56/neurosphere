"""Notification channels, subscriptions, outbox and scope resolution (PRP-107 item 2)."""

from neurosphere_core.notifications.message import (
    NotificationMessage,
    build_message,
    safe_title,
)
from neurosphere_core.notifications.models import (
    EVENT_CLASSES,
    NotificationChannel,
    NotificationDelivery,
    NotificationEvent,
    NotificationsSetting,
    NotificationSubscription,
    RetryPolicy,
)
from neurosphere_core.notifications.outbox import (
    InMemoryOutboxStore,
    Outbox,
    OutboxEntry,
    OutboxStore,
    compute_dedup_key,
)
from neurosphere_core.notifications.ports import Sender, SendOutcome
from neurosphere_core.notifications.publisher import NotificationPublisher
from neurosphere_core.notifications.registry import ChannelRegistry, SubscriptionRecord
from neurosphere_core.notifications.resolver import (
    DeliveryDecision,
    ResolvedTarget,
    SubscriptionResolver,
)

__all__ = [
    "EVENT_CLASSES",
    "ChannelRegistry",
    "DeliveryDecision",
    "InMemoryOutboxStore",
    "NotificationChannel",
    "NotificationDelivery",
    "NotificationEvent",
    "NotificationMessage",
    "NotificationPublisher",
    "NotificationSubscription",
    "NotificationsSetting",
    "Outbox",
    "OutboxEntry",
    "OutboxStore",
    "ResolvedTarget",
    "RetryPolicy",
    "SendOutcome",
    "Sender",
    "SubscriptionRecord",
    "SubscriptionResolver",
    "build_message",
    "compute_dedup_key",
    "safe_title",
]
