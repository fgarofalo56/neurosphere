"""Ingest and scan edge status (optional components) and the producer registry store (PRP-41).

``main.create`` runs the existing opt-in bootstraps (``configure_ingest_from_settings``,
``configure_scan_from_settings``) before ``compose_app``; this builder reports what they
installed: ``ok`` when the service is on ``app.state``, else ``disabled``. A bootstrap that is
misconfigured still fails startup, as before.

``admin_producers`` (optional, PRP-41) exists only when ``NS_INGEST_PRODUCER_STORE`` is true (the
bootstrap put a ``StoreProducerRegistry`` on ``app.state.ingest_producer_store``). It builds
``ProducerAdmin`` over the ``admin_config`` repository (``backend("admin_config_repository")``,
else Cosmos on the shared client, else in-memory under ``NS_ENV=local`` only), installs the
admin plane and attaches the store layer through an ``on_startup`` hook: one refresh, then a
refresher task cancelled at shutdown. A store that is down at startup never stops the app: file
producers keep authenticating, store-only producers fail closed until a refresh succeeds.
Switch off, no audit store or no customer: ``disabled`` with a logged reason code.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from neurosphere_core.admin import (
    ADMIN_CONFIG_CONTAINER,
    MAX_LIST_LIMIT,
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
)
from neurosphere_core.admin.producers import PRODUCER_KIND, ProducerAdmin

from neurosphere_api.admin.sources.producers import ProducerAdminPlane, configure_producer_admin
from neurosphere_api.ingest.producer_store import (
    StoreProducerRegistry,
    run_refresher,
    stop_refresher,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("ingest", "scan", "admin_producers")
_STATE_KEYS: Final = {"ingest": "ingest_service", "scan": "scan_service"}
_log = logging.getLogger("neurosphere_api.runtime")


def _repository(ctx: BuildContext) -> AdminConfigRepository:
    cloud = ctx.settings.cloud_profile.cloud.value
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return override
    try:
        client = ctx.cosmos_client()
    except ComponentUnavailableError:
        if ctx.settings.env != "local":
            raise
        return InMemoryAdminConfigRepository(cloud=cloud)  # type: ignore[arg-type]
    return CosmosAdminConfigRepository.from_client(
        client,
        database=ctx.store_settings().database,
        container=ADMIN_CONFIG_CONTAINER,
        cloud=cloud,  # type: ignore[arg-type]
    )


def _build_producers(ctx: BuildContext, store: StoreProducerRegistry) -> None:
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    if audit is None:
        _log.warning("component admin_producers disabled: audit_unavailable")
        ctx.disabled("admin_producers")
        return
    customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    if customer is None:
        _log.warning("component admin_producers disabled: customer_unconfigured")
        ctx.disabled("admin_producers")
        return
    try:
        repository = _repository(ctx)
    except ComponentUnavailableError as exc:
        # Cosmos not configured: file producers keep working, the admin API stays off (reason
        # code logged, never a message). Readiness is not blocked (the store layer is optional).
        _log.warning("component admin_producers disabled: %s", exc.reason)
        ctx.disabled("admin_producers")
        return
    ctx.ok("admin_producers")
    cloud = ctx.settings.cloud_profile.cloud.value
    admin = ProducerAdmin(repository, cloud=cloud)  # type: ignore[arg-type]
    configure_producer_admin(
        ctx.app, ProducerAdminPlane(admin=admin, audit=audit, on_change=store.apply)
    )
    interval = float(getattr(ctx.app.state, "ingest_producer_refresh_seconds", 30.0))
    tasks: list[asyncio.Task[None]] = []

    async def load():  # type: ignore[no-untyped-def]
        return await repository.list_by_kind(
            customer, PRODUCER_KIND, include_retired=True, limit=MAX_LIST_LIMIT
        )

    async def start() -> None:
        await store.refresh(load)  # never raises; records a reason code
        if store.last_reason is not None:
            _log.warning("component admin_producers refresh: %s", store.last_reason)
        tasks.append(asyncio.create_task(run_refresher(store, load, interval)))

    async def stop() -> None:
        for task in tasks:
            await stop_refresher(task)

    ctx.on_startup(start)
    ctx.on_shutdown(stop)


def build(ctx: BuildContext) -> None:
    for name, key in _STATE_KEYS.items():
        if getattr(ctx.app.state, key, None) is not None:
            ctx.ok(name)
        else:
            ctx.disabled(name)
    store = getattr(ctx.app.state, "ingest_producer_store", None)
    if isinstance(store, StoreProducerRegistry):
        _build_producers(ctx, store)
    else:
        ctx.disabled("admin_producers")


BUILDER: Final = BuilderSpec("edge", COMPONENTS, build)
