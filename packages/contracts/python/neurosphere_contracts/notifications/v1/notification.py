# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ...actions.v1 import target_ref
from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from ...policy.v1 import policy_definition
from . import notification_subscription


class NotificationDelivery(BaseModel):
    """
    One queued or sent notification (PRP-99; container notification_outbox). Metadata only: a short title and an application-relative link. There is no recipient address, no body and no content of any kind; recipients resolve inside the sender and are never stored. Named NotificationDelivery to avoid the DOM Notification type.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    notification_id: audit_record.Uuid
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    channel_id: common_1.Slug
    subscription_id: common_1.Slug
    event_class: notification_subscription.NotificationEventClass
    severity: policy_definition.PolicySeverity
    subject: target_ref.TargetRef
    title: Annotated[
        StrictStr,
        Field(max_length=160, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$"),
    ]
    """
    Short headline, 1 to 160 characters, no control characters.
    """
    link: Annotated[StrictStr, Field(pattern="^/[A-Za-z0-9/_.=?&%:-]{0,511}$")]
    """
    Application-relative path to the item in the console, never an absolute URL.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]
    dedup_key: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    Digest of event class, subject and channel so one event is one delivery inside the dedup window.
    """
    status: Literal["pending", "sending", "delivered", "failed", "dead_lettered", "suppressed"]
    attempts: Annotated[StrictInt, Field(ge=0, le=20)]
    next_attempt_at: common.Timestamp | None = None
    last_error_code: common_1.ReasonCode | None = None
    created_at: common.Timestamp
    delivered_at: common.Timestamp | None = None
    source_audit_id: audit_record.Uuid | None = None
    """
    Audit record of the event that caused the notification.
    """
