"""``build_azure_monitor_ai``: the role builder (part of ``all``; idles until configured).

``runtime.factories`` imports this module, so the factories-side helpers (Cosmos client,
checkpoint store, tick wrapper) are imported lazily inside the builder to avoid an import cycle.
Settings come from ``resolve_azure_monitor_ai_settings``: the stored configuration wins, a
disabled one idles the role, and with no stored record the environment is used (as gateway_poll).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from neurosphere_core.clients import ClientLifetime

from neurosphere_workers.ingestion.azure_monitor_ai.poller import AzureMonitorAiPoller
from neurosphere_workers.ingestion.gateway_poll import IngestClient, default_connector_factory
from neurosphere_workers.runtime.adapters import PeriodicTick
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.supervisor import RoleRunnable
from neurosphere_workers.sources_status import (
    StatusRecordingTick,
    cosmos_repository,
    idle_recording,
)

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["build_azure_monitor_ai"]

logger = logging.getLogger("neurosphere.workers.runtime")


async def build_azure_monitor_ai(cfg: RuntimeConfig, lifetime: ClientLifetime) -> RoleRunnable:
    # Lazy: connector_config.stored imports this package's settings (import cycle).
    from neurosphere_workers.connector_config import (
        ConnectorIdle,
        resolve_azure_monitor_ai_settings,
    )

    # Lazy: factories imports this module at load time.
    from neurosphere_workers.runtime import factories

    # pyright: ignore comments below: the factories helpers are module-private by convention.
    cosmos_client = factories._cosmos  # pyright: ignore[reportPrivateUsage]
    tick_role = factories._tick_role  # pyright: ignore[reportPrivateUsage]
    checkpoint_store = factories._runtime_checkpoints  # pyright: ignore[reportPrivateUsage]
    closable_http = factories._ClosableHttp  # pyright: ignore[reportPrivateUsage]

    settings = await resolve_azure_monitor_ai_settings(cfg, lifetime)
    status_repo = cosmos_repository(
        lambda: cosmos_client(cfg, lifetime), database=cfg.store.database
    )
    if isinstance(settings, ConnectorIdle) or settings.unconfigured:
        logger.info(
            "azure_monitor_ai not configured; role idles",
            extra={"event": "worker.azure_monitor_ai_unconfigured"},
        )
        idle = idle_recording(
            "azure_monitor_ai", settings, status_repo, customer_id=cfg.customer_id
        )
        return tick_role("azure_monitor_ai", idle, cfg)
    if settings.domain_id is None:
        raise RoleConfigError("azure_monitor_ai_domain_id_missing")
    if settings.api_base_url is None:
        raise RoleConfigError("azure_monitor_ai_api_base_url_missing")
    if settings.producer_secret is None:
        raise RoleConfigError("azure_monitor_ai_producer_secret_missing")
    if not settings.workspaces:
        raise RoleConfigError("azure_monitor_ai_workspace_ids_missing")
    customer = cfg.customer_id
    cosmos = await cosmos_client(cfg, lifetime)
    http = lifetime.register(closable_http(httpx.AsyncClient(timeout=httpx.Timeout(30.0))))
    poller = AzureMonitorAiPoller(
        ingest=IngestClient(
            http.client,
            base_url=settings.api_base_url,
            producer_id=settings.producer_id,
            secret=settings.producer_secret.get_secret_value(),
        ),
        checkpoints=checkpoint_store(cfg, cosmos),
        settings=settings,
        customer_id=customer,
        domain_id=settings.domain_id,
        cloud="government" if cfg.cloud == "government" else "commercial",
        # The factory takes no managed identity client id yet: the default credential is used.
        connector_factory=default_connector_factory(settings.allow_unverified_government),
    )
    recorded = StatusRecordingTick(
        "azure_monitor_ai",
        poller.tick,
        lambda: poller.last_status,
        status_repo,
        customer_id=customer,
    )
    return tick_role("azure_monitor_ai", PeriodicTick(recorded, settings.interval_seconds), cfg)
