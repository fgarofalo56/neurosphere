"""Notification interface and stub email / Teams adapters (PRP-17 clarification 6).

Real delivery is out of scope. The stubs RECORD each send as an audit record on the item's domain
chain and return ``status="recorded"``. A recorded send is not proof of delivery: the receipt has
no ``delivered`` or ``read`` status, and nothing may mark an escalation notified-and-read. The
stubs import no network library and open no socket (tested).

A notification carries references only: the recipient is a pseudonym or a routing ref
(``escalation.level-2``), never an e-mail address, UPN or display name. The audit record holds a
digest of the notification, not its fields.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.audit import AuditRepository, build_after, make_subject, sha256_digest
from neurosphere_core.hitl.auditing import (
    ENTITY_TYPE,
    SYSTEM_ACTOR,
    SYSTEM_SCOPE_HASH,
    audit_chain_for,
    audit_context,
)

__all__ = [
    "EmailNotifierStub",
    "Notification",
    "NotificationEvent",
    "NotificationReceipt",
    "Notifier",
    "RecordingNotifierStub",
    "TeamsNotifierStub",
]

NotificationEvent = Literal[
    "review_assigned",
    "assignment_timed_out",
    "review_escalated",
    "escalation_capped",
    "review_expired",
]
NotifierChannel = Literal["email", "teams"]

_UUID: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_REF: Final = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_CANON: Final = r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_id: Annotated[str, Field(pattern=_UUID)]
    event: NotificationEvent
    review_item_id: Annotated[str, Field(pattern=_UUID)]
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    domain_id: Annotated[str, Field(pattern=_CANON, max_length=512)]
    recipient_ref: Annotated[str, Field(pattern=_REF)]
    """Pseudonym or routing reference; never an address."""
    escalation_level: Annotated[int, Field(ge=0)] = 0
    correlation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]


class NotificationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_id: str
    channel: NotifierChannel
    status: Literal["recorded"]
    """The only status a stub can report. Delivery and read receipts do not exist here."""
    audit_id: str
    recorded_at: AwareDatetime


@runtime_checkable
class Notifier(Protocol):
    channel: NotifierChannel

    async def send(self, notification: Notification) -> NotificationReceipt: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordingNotifierStub:
    """Shared stub body: write one audit record, return a ``recorded`` receipt. No I/O else."""

    channel: NotifierChannel

    def __init__(self, audit: AuditRepository, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._audit = audit
        self._clock = clock

    async def send(self, notification: Notification) -> NotificationReceipt:
        ctx = audit_context(
            actor=SYSTEM_ACTOR,
            scope_hash=SYSTEM_SCOPE_HASH,
            correlation_id=notification.correlation_id,
            operation=f"hitl.notify.{self.channel}",
            channel="worker",
        )
        subject = make_subject(
            f"{notification.cloud}:{notification.customer_id}:hitl:{ENTITY_TYPE}:"
            f"{notification.review_item_id}",
            ENTITY_TYPE,
            state_digest=sha256_digest(notification.model_dump(mode="json")),
        )
        record = await self._audit.append(
            audit_chain_for(notification.customer_id, notification.domain_id),
            build_after(
                ctx,
                subject,
                result="succeeded",
                verified=False,  # recorded, not delivered: nothing was read back
                detail=f"notify.{self.channel}.{notification.event}=recorded",
            ),
        )
        return NotificationReceipt(
            notification_id=notification.notification_id,
            channel=self.channel,
            status="recorded",
            audit_id=record.audit_id.root,
            recorded_at=self._clock(),
        )


class EmailNotifierStub(RecordingNotifierStub):
    channel: NotifierChannel = "email"


class TeamsNotifierStub(RecordingNotifierStub):
    channel: NotifierChannel = "teams"
