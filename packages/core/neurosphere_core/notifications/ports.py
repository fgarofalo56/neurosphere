"""Sender port. Implementations live under ``notifications/senders`` (PRP-107 item 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from neurosphere_core.notifications.message import NotificationMessage
from neurosphere_core.notifications.models import NotificationChannel

__all__ = ["SendOutcome", "Sender"]


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """Result of one send attempt: a status code and a machine reason code, never a body."""

    status_code: int | None = None
    reason_code: str | None = None
    retryable: bool = False

    @property
    def delivered(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300


@runtime_checkable
class Sender(Protocol):
    async def send(
        self, channel: NotificationChannel, message: NotificationMessage, *, notification_id: str
    ) -> SendOutcome:
        """Deliver ``message`` through ``channel``; never raises for a delivery failure."""
        ...
