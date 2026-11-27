"""Notification senders (PRP-107 item 4): signed webhook and Teams Workflows card."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting

from neurosphere_core.notifications.egress import EgressGuard
from neurosphere_core.notifications.ports import Sender
from neurosphere_core.notifications.senders.base import SecretReader
from neurosphere_core.notifications.senders.kinds import (
    KIND_STATUS,
    KindNotBuildableError,
    KindStatus,
    kind_status,
    require_buildable,
)
from neurosphere_core.notifications.senders.teams import TeamsWorkflowSender
from neurosphere_core.notifications.senders.webhook import WebhookSender, verify_signature

__all__ = [
    "KIND_STATUS",
    "KindNotBuildableError",
    "KindStatus",
    "SecretReader",
    "TeamsWorkflowSender",
    "WebhookSender",
    "build_sender",
    "kind_status",
    "require_buildable",
    "verify_signature",
]


def build_sender(
    kind: str,
    guard: EgressGuard,
    secrets: SecretReader,
    *,
    setting: NotificationsSetting,
    deployment_cloud: str,
    ns_env: str,
    clock: Callable[[], datetime],
) -> Sender:
    """Sender for ``kind``; raises :class:`KindNotBuildableError` for a not-built kind."""
    require_buildable(kind)
    cls = WebhookSender if kind == "webhook" else TeamsWorkflowSender
    return cls(
        guard,
        secrets,
        setting=setting,
        deployment_cloud=deployment_cloud,
        ns_env=ns_env,
        clock=clock,
    )
