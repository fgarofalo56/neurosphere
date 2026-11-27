"""Response models of the notification admin routes (PRP-107 item 7).

A view wraps the stored contract document with its ``admin_config`` envelope facts (version,
ETag, writer, time). Credentials appear only as the contract's reference object (a Key Vault
secret identifier or a managed identity id), never a value. No ``from __future__ import
annotations``: FastAPI builds response models from these classes.
"""

from typing import Any, Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

__all__ = [
    "DELIVERY_STATUSES",
    "ChannelList",
    "ChannelTestResult",
    "ChannelView",
    "DeliveryCounts",
    "DeliveryList",
    "KindInfo",
    "KindList",
    "SubscriptionList",
    "SubscriptionView",
    "etag_of",
    "quoted",
]

DELIVERY_STATUSES: Final = (
    "pending",
    "sending",
    "delivered",
    "failed",
    "dead_lettered",
    "suppressed",
)


def quoted(etag: str) -> str:
    """An entity tag in its quoted wire form."""
    return etag if etag.startswith('"') else f'"{etag}"'


def etag_of(document: AdminConfigDocument) -> str:
    return quoted(document.etag.root)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KindInfo(_Model):
    kind: str
    status: str
    reason: str | None


class KindList(_Model):
    items: list[KindInfo]


class DeliveryCounts(_Model):
    pending: StrictInt = 0
    sending: StrictInt = 0
    delivered: StrictInt = 0
    failed: StrictInt = 0
    dead_lettered: StrictInt = 0
    suppressed: StrictInt = 0


class ChannelView(_Model):
    #: The contract NotificationChannel as JSON: an open object here, because the contract classes
    #: would rename shared OpenAPI components; the service validates it as the contract type.
    channel: dict[str, Any]
    version: StrictInt
    etag: str
    updated_at: str
    updated_by: str
    delivery_counts: DeliveryCounts
    last_error_code: str | None = None


class ChannelList(_Model):
    items: list[ChannelView]


class SubscriptionView(_Model):
    #: The contract NotificationSubscription as JSON (see ChannelView.channel).
    subscription: dict[str, Any]
    version: StrictInt
    etag: str
    updated_at: str
    updated_by: str


class SubscriptionList(_Model):
    items: list[SubscriptionView]


class DeliveryList(_Model):
    #: Contract NotificationDelivery rows as JSON (metadata only: no body, no recipient).
    items: list[dict[str, Any]]


class ChannelTestResult(_Model):
    ok: StrictBool
    status_code: int | None = Field(default=None)
    reason_code: str | None = Field(default=None)
