"""Recipient scope: which subscriptions may be told about an event, at publish and at delivery.

Publish-time rule, all of which must hold for a subscription to produce an outbox row:

* the subscription and its channel are enabled and neither is retired;
* both belong to the event's customer and cloud, and the subscription's ``domain_id`` and the
  channel's ``domain_id`` equal the event's ``domain_id`` (a subscription scoped to one domain is
  never offered another domain's event);
* the event class is in ``event_classes`` and the event severity is at least ``min_severity``;
* the subscription OWNER (see :mod:`.registry`) currently holds ``data.read`` on the event's
  domain, asked of the permission recheck port (a revoked or unknown principal is denied);
* every role in ``audience_roles`` itself confers ``data.read`` (see below).

A subscription that fails any test produces NO row, so nothing about the event (its id or title)
is written against a channel scoped elsewhere. Any recheck error fails closed: no row.

``audience_roles`` reading. The contract says the roles are the people who receive the
notification and that recipients are resolved at the sender from the roles and never stored. This
platform's channels are group-addressed (no per-person address exists), so the role list cannot
pick individuals; it states WHO the channel audience is. The scope rule therefore applies to the
role names: a message about a domain's entity is deliverable only to roles that may read that
domain's data. A subscription naming a role without ``data.read`` (for example
``security_auditor``) is refused as a whole rather than silently narrowed, so a configuration
cannot widen the audience beyond readers. The roles never grant anything.

:meth:`SubscriptionResolver.recheck_for_delivery` repeats the scope test when the worker is about
to send. A lost scope is a ``suppress`` decision (reason ``scope``); a recheck that cannot be
answered is neither a send nor a suppression (``allowed=False``, ``suppress=False``): the worker
leaves the row to retry, so an outage never delivers and never silently drops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from neurosphere_core.actions.permissions import PermissionRechecker
from neurosphere_core.auth.scope import Permission, role_permissions
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.notifications.models import (
    EVENT_CLASSES,
    SEVERITY_ORDER,
    NotificationChannel,
    NotificationDelivery,
    NotificationEvent,
    NotificationSubscription,
    severity_at_least,
    unknown_event_class,
)
from neurosphere_core.notifications.registry import ChannelRegistry, SubscriptionRecord

__all__ = ["DeliveryDecision", "ResolvedTarget", "SubscriptionResolver"]

_LOG: Final = logging.getLogger(__name__)
_READ: Final = "data.read"
SCOPE_REASON: Final = "scope"
RECHECK_UNAVAILABLE: Final = "recheck_unavailable"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    subscription: SubscriptionRecord
    channel: NotificationChannel


@dataclass(frozen=True, slots=True)
class DeliveryDecision:
    """``allowed`` -> send; ``suppress`` -> mark the row ``suppressed`` with ``reason``;
    neither -> leave the row for a later attempt."""

    allowed: bool
    suppress: bool
    reason: str | None = None
    channel: NotificationChannel | None = None


def _roles_may_read(roles: list[str]) -> bool:
    return all(Permission.DATA_READ in role_permissions(role) for role in roles)


class SubscriptionResolver:
    def __init__(self, registry: ChannelRegistry, rechecker: PermissionRechecker) -> None:
        self._registry = registry
        self._rechecker = rechecker

    async def resolve(self, event: NotificationEvent) -> list[ResolvedTarget]:
        """Targets for ``event``; an unknown class or severity is refused, never matched."""
        if event.event_class not in EVENT_CLASSES:
            raise unknown_event_class()
        if event.severity not in SEVERITY_ORDER:
            raise InvalidSchemaError(
                "severity is not a policy severity",
                errors=[ValidationIssue("/severity", "unknown severity")],
                reason="unknown_severity",
            )
        records = await self._registry.subscriptions(event.customer_id)
        owner_ok: dict[str, bool] = {}
        targets: list[ResolvedTarget] = []
        for record in records:
            sub = record.subscription
            if not self._matches(sub, event):
                continue
            channel = await self._registry.channel(event.customer_id, sub.channel_id.root)
            if channel is None or not self._channel_matches(channel, event):
                continue
            if not _roles_may_read([r.root for r in sub.audience_roles]):
                continue
            owner = record.owner_principal_id
            if owner not in owner_ok:
                owner_ok[owner] = await self._owner_reads(owner, event.customer_id, event.domain_id)
            if owner_ok[owner]:
                targets.append(ResolvedTarget(record, channel))
        return targets

    async def recheck_for_delivery(self, row: NotificationDelivery) -> DeliveryDecision:
        """Scope test at send time, from the row's ids only."""
        customer = row.customer_id.root
        record = await self._registry.subscription(customer, row.subscription_id.root)
        if record is None or not record.subscription.enabled:
            return DeliveryDecision(False, True, SCOPE_REASON)
        sub = record.subscription
        channel = await self._registry.channel(customer, row.channel_id.root)
        if (
            channel is None
            or not channel.enabled
            or sub.channel_id.root != row.channel_id.root
            or sub.domain_id.root != row.domain_id.root
            or channel.domain_id.root != row.domain_id.root
            or not _roles_may_read([r.root for r in sub.audience_roles])
        ):
            return DeliveryDecision(False, True, SCOPE_REASON)
        try:
            granted = await self._rechecker.check(
                record.owner_principal_id, customer, row.domain_id.root, _READ
            )
        except Exception:
            _LOG.warning("notification scope recheck unavailable", extra={"reason": "recheck"})
            return DeliveryDecision(False, False, RECHECK_UNAVAILABLE)
        if not granted:
            return DeliveryDecision(False, True, SCOPE_REASON)
        return DeliveryDecision(True, False, None, channel)

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _matches(sub: NotificationSubscription, event: NotificationEvent) -> bool:
        minimum = sub.min_severity.root if sub.min_severity is not None else "medium"
        return (
            sub.enabled
            and sub.customer_id.root == event.customer_id
            and sub.cloud.root == event.cloud
            and sub.domain_id.root == event.domain_id
            and event.event_class in {c.root for c in sub.event_classes}
            and severity_at_least(event.severity, minimum)
        )

    @staticmethod
    def _channel_matches(channel: NotificationChannel, event: NotificationEvent) -> bool:
        return (
            channel.enabled
            and channel.customer_id.root == event.customer_id
            and channel.cloud.root == event.cloud
            and channel.domain_id.root == event.domain_id
        )

    async def _owner_reads(self, owner: str, customer_id: str, domain_id: str) -> bool:
        try:
            return await self._rechecker.check(owner, customer_id, domain_id, _READ)
        except Exception:
            _LOG.warning("notification scope recheck unavailable", extra={"reason": "recheck"})
            return False
