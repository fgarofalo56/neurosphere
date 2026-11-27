"""Channel, subscription and notification-setting reads over ``admin_config`` documents.

Documents of kinds ``notification_channel`` and ``notification_subscription`` (and the
``notifications`` system setting) are written by the admin routes through the shared
:class:`~neurosphere_core.admin.store.AdminConfigRepository`; this module only reads. A retired
document is treated as absent. A subscription's OWNER is the envelope's ``updated_by`` principal
(the pseudonymous principal that made the accepted write): re-saving a subscription transfers
ownership to the editor, which is the conservative reading because the editor's scope vouches for
the current content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument

from neurosphere_core.admin.store import MAX_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.notifications.models import (
    NotificationChannel,
    NotificationsSetting,
    NotificationSubscription,
    RetryPolicy,
)

__all__ = ["ChannelRegistry", "SubscriptionRecord"]

CHANNEL_KIND: Final = "notification_channel"
SUBSCRIPTION_KIND: Final = "notification_subscription"
SETTING_KIND: Final = "system_setting"
SETTING_ID: Final = "notifications"


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    subscription: NotificationSubscription
    owner_principal_id: str
    etag: str


class ChannelRegistry:
    """Read-side view of channels, subscriptions and retry settings for one deployment."""

    def __init__(self, repository: AdminConfigRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> AdminConfigRepository:
        """The ``admin_config`` store, for the admin routes that write the documents."""
        return self._repo

    async def channel(self, customer_id: str, channel_id: str) -> NotificationChannel | None:
        doc = await self._repo.get(customer_id, CHANNEL_KIND, channel_id)
        if doc is None or doc.status != "active":
            return None
        return cast(NotificationChannel, doc.body)

    async def channels(self, customer_id: str) -> list[NotificationChannel]:
        docs = await self._repo.list_by_kind(customer_id, CHANNEL_KIND, limit=MAX_LIST_LIMIT)
        return [cast(NotificationChannel, d.body) for d in docs if d.status == "active"]

    async def subscription(
        self, customer_id: str, subscription_id: str
    ) -> SubscriptionRecord | None:
        doc = await self._repo.get(customer_id, SUBSCRIPTION_KIND, subscription_id)
        if doc is None or doc.status != "active":
            return None
        return _record(doc)

    async def subscriptions(self, customer_id: str) -> list[SubscriptionRecord]:
        docs = await self._repo.list_by_kind(customer_id, SUBSCRIPTION_KIND, limit=MAX_LIST_LIMIT)
        return [_record(d) for d in docs if d.status == "active"]

    async def settings(self, customer_id: str) -> NotificationsSetting | None:
        doc = await self._repo.get(customer_id, SETTING_KIND, SETTING_ID)
        if doc is None or doc.status != "active":
            return None
        return cast("NotificationsSetting | None", getattr(doc.body, "notifications", None))

    async def retry_policy(self, customer_id: str) -> RetryPolicy:
        return RetryPolicy.from_setting(await self.settings(customer_id))


def _record(doc: AdminConfigDocument) -> SubscriptionRecord:
    return SubscriptionRecord(
        subscription=cast(NotificationSubscription, doc.body),
        owner_principal_id=doc.updated_by.root,
        etag=doc.etag.root,
    )
