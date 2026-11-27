"""``NotificationPublisher``: resolve recipients by scope, then enqueue de-duplicated rows."""

from __future__ import annotations

from neurosphere_core.notifications.models import NotificationDelivery, NotificationEvent
from neurosphere_core.notifications.outbox import Outbox
from neurosphere_core.notifications.registry import ChannelRegistry
from neurosphere_core.notifications.resolver import SubscriptionResolver

__all__ = ["NotificationPublisher"]


class NotificationPublisher:
    """Publish one event: one ``pending`` row per matching subscription, none for duplicates."""

    def __init__(
        self, resolver: SubscriptionResolver, outbox: Outbox, registry: ChannelRegistry
    ) -> None:
        self._resolver = resolver
        self._outbox = outbox
        self._registry = registry

    async def publish(self, event: NotificationEvent) -> list[NotificationDelivery]:
        """Rows CREATED by this call (a duplicate inside the window creates and returns none).

        Raises ``invalid_schema`` (``unknown_event_class``) for a class outside the contract enum.
        """
        targets = await self._resolver.resolve(event)
        if not targets:
            return []
        window = event.dedup_window_seconds
        if window is None:
            window = (await self._registry.retry_policy(event.customer_id)).dedup_window_seconds
        created: list[NotificationDelivery] = []
        for target in targets:
            entry, was_created = await self._outbox.enqueue(
                event,
                subscription_id=target.subscription.subscription.subscription_id.root,
                channel_id=target.channel.channel_id.root,
                window_seconds=window,
            )
            if was_created:
                created.append(entry.delivery)
        return created
