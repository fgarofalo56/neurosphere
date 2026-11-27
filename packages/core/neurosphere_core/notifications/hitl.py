"""``OutboxNotifier``: the HITL ``Notifier`` that queues a notification in the outbox (PRP-107).

Each HITL ``Notification`` becomes one ``NotificationEvent`` of class ``hitl_item_assigned``,
``hitl_item_escalated`` or ``hitl_item_expiring``, published through the ``NotificationPublisher``
(subscription scope, dedup, one ``pending`` row per matching subscription). The event holds ids, a
fixed short title and an application-relative link to the review item: no prompt, no item
payload, no reason text, no recipient address.

The receipt says ``recorded``: queued in the outbox, NOT delivered. Only the delivery worker ever
writes a ``delivered`` row, so nothing here can claim delivery.

A publish failure is logged by reason code and re-raised as a ``NeuroSphereError`` so the HITL
service counts it in ``notifications_failed`` and carries on: HITL never fails because a
notification could not be queued.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlencode

from neurosphere_contracts.actions.v1.target_ref import TargetRef

from neurosphere_core.errors import DependencyTransientError, NeuroSphereError
from neurosphere_core.hitl.auditing import refusal_code
from neurosphere_core.hitl.notify import (
    Notification,
    NotificationReceipt,
    NotifierChannel,
)
from neurosphere_core.notifications.models import NotificationEvent
from neurosphere_core.notifications.publisher import NotificationPublisher

__all__ = ["OutboxNotifier", "event_for_notification"]

_LOG: Final = logging.getLogger(__name__)

#: HITL event -> (notification event class, severity, fixed title).
_MAP: Final[dict[str, tuple[str, str, str]]] = {
    "review_assigned": ("hitl_item_assigned", "medium", "Review item assigned"),
    "assignment_timed_out": ("hitl_item_expiring", "medium", "Review assignment timed out"),
    "review_escalated": ("hitl_item_escalated", "high", "Review item escalated"),
    "escalation_capped": ("hitl_item_escalated", "high", "Review escalation capped"),
    "review_expired": ("hitl_item_expiring", "high", "Review item expired"),
}
_ENTITY_TYPE: Final = "review_item"
_NO_ROW: Final = "none"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def event_for_notification(notification: Notification) -> NotificationEvent:
    """The publish input for one HITL notification (ids only, no content)."""
    event_class, severity, title = _MAP[notification.event]
    link = "/review/item?" + urlencode(
        {"domain_id": notification.domain_id, "item_id": notification.review_item_id}
    )
    return NotificationEvent(
        event_class=event_class,
        customer_id=notification.customer_id,
        cloud=notification.cloud,
        domain_id=notification.domain_id,
        subject=TargetRef(
            canonical_id=(
                f"{notification.cloud}:{notification.customer_id}:hitl:{_ENTITY_TYPE}:"
                f"{notification.review_item_id}"
            ),
            entity_type=_ENTITY_TYPE,
        ),
        title=title,
        severity=severity,
        link=link,
        correlation_id=notification.correlation_id,
        dedup_key=(
            f"hitl:{notification.event}:{notification.review_item_id}:"
            f"{notification.recipient_ref}:{notification.escalation_level}"
        ),
    )


class OutboxNotifier:
    channel: NotifierChannel = "outbox"

    def __init__(
        self,
        publisher: NotificationPublisher,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._publisher = publisher
        self._clock = clock

    async def send(self, notification: Notification) -> NotificationReceipt:
        try:
            rows = await self._publisher.publish(event_for_notification(notification))
        except NeuroSphereError as exc:
            _LOG.warning(
                "hitl notification not queued",
                extra={"event": "hitl.outbox_failed", "reason": refusal_code(exc)},
            )
            raise
        except Exception as exc:
            _LOG.warning(
                "hitl notification not queued",
                extra={"event": "hitl.outbox_failed", "reason": type(exc).__name__},
            )
            raise DependencyTransientError(reason="notification_publish_failed") from None
        return NotificationReceipt(
            notification_id=notification.notification_id,
            channel=self.channel,
            status="recorded",
            audit_id=rows[0].notification_id.root if rows else _NO_ROW,
            recorded_at=self._clock(),
        )
