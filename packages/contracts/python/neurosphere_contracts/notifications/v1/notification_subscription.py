# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool

from ...admin.v1 import common as common_1
from ...catalog.v1 import common
from ...policy.v1 import policy_definition


class NotificationEventClass(
    RootModel[
        Literal[
            "policy_violation_opened",
            "policy_violation_escalated",
            "policy_violation_resolved",
            "policy_exception_requested",
            "policy_exception_decided",
            "hitl_item_assigned",
            "hitl_item_escalated",
            "hitl_item_expiring",
            "approval_requested",
            "approval_decided",
            "action_executed",
            "action_failed",
            "capture_policy_changed",
            "enforcement_mode_changed",
            "budget_threshold_crossed",
            "channel_delivery_failed",
        ]
    ]
):
    root: Annotated[
        Literal[
            "policy_violation_opened",
            "policy_violation_escalated",
            "policy_violation_resolved",
            "policy_exception_requested",
            "policy_exception_decided",
            "hitl_item_assigned",
            "hitl_item_escalated",
            "hitl_item_expiring",
            "approval_requested",
            "approval_decided",
            "action_executed",
            "action_failed",
            "capture_policy_changed",
            "enforcement_mode_changed",
            "budget_threshold_crossed",
            "channel_delivery_failed",
        ],
        Field(title="NotificationEventClass"),
    ]
    """
    What happened; open-ended: readers must tolerate unknown values.
    """


class NotificationSubscription(BaseModel):
    """
    Which event classes reach which channel and for which audience roles (PRP-99; body of admin_kind notification_subscription). Recipients are resolved inside the sender from the roles and are never stored.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    subscription_id: common_1.Slug
    """
    Subscription id (slug).
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    channel_id: common_1.Slug
    """
    Channel this subscription delivers to.
    """
    event_classes: Annotated[list[NotificationEventClass], Field(max_length=16, min_length=1)]
    audience_roles: Annotated[list[common_1.Role], Field(max_length=6, min_length=1)]
    """
    Roles whose members receive the notification.
    """
    min_severity: Annotated[
        policy_definition.PolicySeverity | None, Field(validate_default=True)
    ] = "medium"
    """
    Lowest severity delivered.
    """
    enabled: StrictBool
