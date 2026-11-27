"""Wiring of the ``notifications`` role (PRP-107 item 5): ``BUILDERS["notifications"]``.

Built from the public client factories only (``runtime.factories`` imports this module for its
``BUILDERS`` table, so importing its private helpers here would be circular):

* Cosmos ``notification_outbox`` (``CosmosOutboxStore``) and ``admin_config`` (channels,
  subscriptions and the ``notifications`` setting, read through ``ChannelRegistry``);
* the scope recheck: ``SubscriptionResolver`` over the SHARED permission rechecker
  (:func:`~neurosphere_workers.runtime.rechecker.build_permission_rechecker`, the construction the
  ``actions`` role uses), so the delivery-time test reads the same policy and revocation stores;
* the Key Vault reader of the connector roles (workload identity, never a key) for channel
  credentials, and the real :class:`EgressGuard`;
* the audit repository for the ``notification.delivery`` record of a failed row.

``NS_ENV`` and the deployment cloud come from the runtime config exactly as the other roles read
them (``cfg.settings.env`` and ``cfg.cloud``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from neurosphere_core.admin import CosmosAdminConfigRepository
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.audit.repository import AuditRepository
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName
from neurosphere_core.notifications import ChannelRegistry, Outbox, SubscriptionResolver
from neurosphere_core.notifications.cosmos_store import CosmosOutboxStore
from neurosphere_core.notifications.egress import EgressGuard
from neurosphere_core.stores import ensure_local_containers

from neurosphere_workers.connector_config.resolve import build_reader
from neurosphere_workers.notifications.worker import ROLE_NAME, NotificationDeliveryWorker
from neurosphere_workers.runtime.adapters import TickWorker, WorkerRole
from neurosphere_workers.runtime.identity import build_policy_stack
from neurosphere_workers.runtime.rechecker import build_permission_rechecker

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig
    from neurosphere_workers.runtime.supervisor import RoleRunnable

__all__ = ["build_notifications"]

_AUDIT_CONTAINER: Final = "audit"
_AUDIT_TAIL_CONTAINER: Final = "audit_tail"
_VAULT_TIMEOUT_SECONDS: Final = 10.0


async def build_notifications(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    customer = cfg.customer_id
    cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime, account=cfg.store.cosmos_account)
    if cfg.settings.env == "local":
        await ensure_local_containers(cosmos, cfg.settings, database=cfg.store.database)
    database = cfg.store.database
    registry = ChannelRegistry(
        CosmosAdminConfigRepository.from_client(
            cosmos,
            database=database,
            cloud=cfg.cloud,  # type: ignore[arg-type]
        )
    )
    stack = build_policy_stack(
        cfg.settings, cosmos=cosmos, auth=cfg.auth, store=cfg.store, tenant_id=cfg.tenant_id
    )
    worker = NotificationDeliveryWorker(
        outbox=Outbox(CosmosOutboxStore.from_client(cosmos, database=database)),
        registry=registry,
        resolver=SubscriptionResolver(registry, build_permission_rechecker(cfg.settings, stack)),
        secrets=build_reader(CloudName(cfg.cloud), client_id=None, timeout=_VAULT_TIMEOUT_SECONDS),
        guard=EgressGuard(),
        audit=AuditRepository(
            CosmosAuditStore.from_client(
                cosmos,
                database=database,
                container=_AUDIT_CONTAINER,
                tail_container=_AUDIT_TAIL_CONTAINER,
            )
        ),
        customer_id=customer,
        ns_env=cfg.settings.env,
        deployment_cloud=cfg.cloud,
    )

    async def tick() -> None:
        await worker.tick()

    return WorkerRole(TickWorker(ROLE_NAME, tick), idle_seconds=cfg.worker.poll_seconds)
