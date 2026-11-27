"""Worker-side publisher wiring shared by the HITL roles and the ``policy_eval`` violation sink.

One construction (``ChannelRegistry`` over ``admin_config``, the Cosmos outbox, a
``SubscriptionResolver`` over the SHARED permission rechecker) so every role that publishes a
notification reads the same stores as the delivery role. ``build_publisher`` returns ``None`` when
the worker has no tenant or key to derive the policy stack from (a role that never needed one
still builds); the caller then runs without a notifier, exactly as before PRP-107.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Final

from neurosphere_core.admin import CosmosAdminConfigRepository
from neurosphere_core.clients.factories import ENV_COSMOS_KEY
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.notifications import (
    ChannelRegistry,
    NotificationPublisher,
    Outbox,
    SubscriptionResolver,
)
from neurosphere_core.notifications.cosmos_store import CosmosOutboxStore
from neurosphere_core.notifications.hitl import OutboxNotifier

from neurosphere_workers.runtime.identity import build_policy_stack
from neurosphere_workers.runtime.rechecker import build_permission_rechecker
from neurosphere_workers.runtime.roles import RoleConfigError

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["build_outbox_notifier", "build_publisher", "notifications_store_configured"]

_LOG: Final = logging.getLogger(__name__)


def notifications_store_configured(cfg: RuntimeConfig) -> bool:
    """A Cosmos account (or, under ``NS_ENV=local``, the emulator key) is set for this role."""
    if cfg.settings.env == "local":
        return bool(os.environ.get(ENV_COSMOS_KEY))
    return cfg.store.cosmos_account is not None


def build_publisher(cfg: RuntimeConfig, cosmos: Any) -> NotificationPublisher | None:
    """The role's publisher, or ``None`` when its policy stack cannot be built."""
    try:
        stack = build_policy_stack(
            cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
        )
    except (RoleConfigError, NeuroSphereError) as exc:
        _LOG.warning(
            "notification publisher not built",
            extra={
                "event": "notifications.publisher_unavailable",
                "reason": getattr(exc, "reason", None) or type(exc).__name__,
            },
        )
        return None
    database = cfg.store.database
    registry = ChannelRegistry(
        CosmosAdminConfigRepository.from_client(
            cosmos,
            database=database,
            cloud=cfg.cloud,  # type: ignore[arg-type]
        )
    )
    return NotificationPublisher(
        SubscriptionResolver(registry, build_permission_rechecker(cfg.settings, stack)),
        Outbox(CosmosOutboxStore.from_client(cosmos, database=database)),
        registry,
    )


def build_outbox_notifier(cfg: RuntimeConfig, cosmos: Any) -> OutboxNotifier | None:
    publisher = build_publisher(cfg, cosmos)
    return OutboxNotifier(publisher) if publisher is not None else None
