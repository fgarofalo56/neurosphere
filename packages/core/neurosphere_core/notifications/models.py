"""Notification bindings: the PRP-99 contract types and the internal publish input.

``NotificationDelivery`` (the outbox row) holds metadata only: ids, a short title and an
application-relative link. There is no recipient address, no body and no content of any kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification import NotificationDelivery
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_contracts.notifications.v1.notification_subscription import (
    NotificationEventClass,
    NotificationSubscription,
)

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "DEFAULT_DEDUP_WINDOW_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BASE_SECONDS",
    "EVENT_CLASSES",
    "MAX_BACKOFF_SECONDS",
    "NOTIFICATION_SCHEMA_VERSION",
    "SEVERITY_ORDER",
    "DeliveryStatus",
    "NotificationChannel",
    "NotificationDelivery",
    "NotificationEvent",
    "NotificationEventClass",
    "NotificationSubscription",
    "NotificationsSetting",
    "RetryPolicy",
    "TargetRef",
    "severity_at_least",
    "unknown_event_class",
]

NOTIFICATION_SCHEMA_VERSION: Final = "1.0.0"
DeliveryStatus = Literal["pending", "sending", "delivered", "failed", "dead_lettered", "suppressed"]

#: Every value the generated ``NotificationEventClass`` allows (no separate registry).
EVENT_CLASSES: Final[frozenset[str]] = frozenset(
    get_args(NotificationEventClass.model_fields["root"].annotation)
)
SEVERITY_ORDER: Final[dict[str, int]] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

DEFAULT_MAX_ATTEMPTS: Final = 8
DEFAULT_RETRY_BASE_SECONDS: Final = 30
DEFAULT_DEDUP_WINDOW_SECONDS: Final = 900
#: Upper bound between two attempts (PRP-107 clarification 9).
MAX_BACKOFF_SECONDS: Final = 900


def severity_at_least(severity: str, minimum: str) -> bool:
    """``True`` when ``severity`` is ``minimum`` or higher; an unknown value is never enough."""
    if severity not in SEVERITY_ORDER or minimum not in SEVERITY_ORDER:
        return False
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[minimum]


def unknown_event_class() -> InvalidSchemaError:
    return InvalidSchemaError(
        "event class is not a notification event class",
        errors=[ValidationIssue("/event_class", "unknown event class")],
        reason="unknown_event_class",
    )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Attempt cap, backoff base and default dedup window (from ``NotificationsSetting``)."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS
    dedup_window_seconds: int = DEFAULT_DEDUP_WINDOW_SECONDS

    @classmethod
    def from_setting(cls, setting: NotificationsSetting | None) -> RetryPolicy:
        if setting is None:
            return cls()
        return cls(
            max_attempts=setting.max_attempts or DEFAULT_MAX_ATTEMPTS,
            retry_base_seconds=setting.retry_base_seconds or DEFAULT_RETRY_BASE_SECONDS,
            dedup_window_seconds=(
                DEFAULT_DEDUP_WINDOW_SECONDS
                if setting.dedup_window_seconds is None
                else setting.dedup_window_seconds
            ),
        )

    def backoff_seconds(self, attempts: int) -> int:
        """Delay before the next attempt after ``attempts`` attempts: base doubling, capped."""
        exponent = max(attempts - 1, 0)
        return min(self.retry_base_seconds * (2 ** min(exponent, 30)), MAX_BACKOFF_SECONDS)


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """Publish input. ``dedup_key`` is the caller's logical-event key (never content)."""

    event_class: str
    customer_id: str
    cloud: str
    domain_id: str
    subject: TargetRef
    title: str
    severity: str
    link: str
    correlation_id: str
    dedup_key: str
    dedup_window_seconds: int | None = None
    source_audit_id: str | None = None
