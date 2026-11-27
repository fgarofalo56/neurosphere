"""Notifications builder (PRP-107 item 6): the API side of the outbox, built once.

Component ``notifications`` is OPTIONAL. It builds, over the shared Cosmos client (or the named
test backends):

* ``registry``: ``ChannelRegistry`` over ``admin_config`` (channels, subscriptions, settings);
* ``store`` / ``outbox``: the ``notification_outbox`` store and its state machine;
* ``resolver``: ``SubscriptionResolver`` over the API's own ``PolicyPermissionRechecker`` (the one
  construction the HITL service uses), so publish-time scope reads the same policy and revocation
  stores;
* ``publisher``: ``NotificationPublisher``;
* ``notifier``: the ``OutboxNotifier`` the data builder hands to ``HitlService``.

The plane is published under :data:`NOTIFICATIONS` and installed on ``app.state.notifications``;
the admin routes (item 7) reuse its ``registry``, ``outbox`` and ``store``. This builder runs
BEFORE ``data`` (it needs only the authz stores), because ``HitlService`` takes its notifiers at
construction. When Cosmos or the authz stores are missing the component is ``disabled`` (reason on
``app.state.notifications_off_reason``) and HITL runs without the outbox notifier.

Test backends: ``admin_config_repository`` (an ``AdminConfigRepository``) and
``notification_outbox_store`` (an ``OutboxStore``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.admin import AdminConfigRepository, CosmosAdminConfigRepository
from neurosphere_core.notifications import (
    ChannelRegistry,
    NotificationPublisher,
    Outbox,
    OutboxStore,
    SubscriptionResolver,
)
from neurosphere_core.notifications.cosmos_store import CosmosOutboxStore
from neurosphere_core.notifications.hitl import OutboxNotifier

from neurosphere_api.runtime.builders import (
    POLICY_REPOSITORY,
    REVOCATION_CHECKER,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
    SharedKey,
)

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "NOTIFICATIONS",
    "NotificationsPlane",
    "build",
]

COMPONENTS: Final = ("notifications",)
_COMPONENT: Final = "notifications"
STATE_ATTRIBUTE: Final = "notifications"
OFF_REASON_ATTRIBUTE: Final = "notifications_off_reason"


@dataclass(frozen=True, slots=True)
class NotificationsPlane:
    """What the API shares: the admin routes read ``registry``/``outbox``/``store``."""

    registry: ChannelRegistry
    store: OutboxStore
    outbox: Outbox
    resolver: SubscriptionResolver
    publisher: NotificationPublisher
    notifier: OutboxNotifier


NOTIFICATIONS: Final[SharedKey[NotificationsPlane]] = SharedKey("notifications")


def _admin_config(ctx: BuildContext) -> AdminConfigRepository:
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return override
    return CosmosAdminConfigRepository.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        cloud=ctx.settings.cloud_profile.cloud.value,  # type: ignore[arg-type]
    )


def _store(ctx: BuildContext) -> OutboxStore:
    override = ctx.overrides.backend("notification_outbox_store")
    if override is not None:
        if not isinstance(override, OutboxStore):
            raise ComponentUnavailableError("notification_outbox_override_invalid")
        return override
    return CosmosOutboxStore.from_client(
        ctx.cosmos_client(), database=ctx.store_settings().database
    )


def _plane(ctx: BuildContext) -> NotificationsPlane:
    policies = ctx.shared(POLICY_REPOSITORY)
    revocation = ctx.shared(REVOCATION_CHECKER)
    clock: Callable[[], float] = ctx.overrides.clock or time.time

    def now() -> datetime:
        return datetime.fromtimestamp(clock(), UTC)

    rechecker = PolicyPermissionRechecker(
        cloud=ctx.settings.cloud_profile.cloud,
        policy_repository=policies,
        revocation_checker=revocation,
        clock=now,
    )
    registry = ChannelRegistry(_admin_config(ctx))
    store = _store(ctx)
    outbox = Outbox(store, clock=now)
    resolver = SubscriptionResolver(registry, rechecker)
    publisher = NotificationPublisher(resolver, outbox, registry)
    return NotificationsPlane(
        registry=registry,
        store=store,
        outbox=outbox,
        resolver=resolver,
        publisher=publisher,
        notifier=OutboxNotifier(publisher, clock=now),
    )


def build(ctx: BuildContext) -> None:
    try:
        plane = _plane(ctx)
    except ComponentUnavailableError as exc:
        setattr(ctx.app.state, OFF_REASON_ATTRIBUTE, exc.reason)
        ctx.disabled(_COMPONENT)
        return
    setattr(ctx.app.state, STATE_ATTRIBUTE, plane)
    ctx.publish(NOTIFICATIONS, plane)
    ctx.ok(_COMPONENT)


BUILDER: Final = BuilderSpec("notifications", COMPONENTS, build)
