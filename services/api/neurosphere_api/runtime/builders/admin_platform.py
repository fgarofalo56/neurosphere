"""Platform admin builder (PRP-44 item 4): installs ``app.state.admin_platform``.

Component ``admin_platform`` is OPTIONAL: a deployment without it still serves (defaults for the
review policy, no domain registry), and the routes answer 503 ``admin_platform_unconfigured``. It
reports ``disabled`` (reason code logged) when the Cosmos client is not available. The audit
repository is read per request: without it every mutation fails closed.

* Stores: ``backend("admin_config_repository")`` or the ``CosmosAdminConfigRepository`` on the ONE
  shared Cosmos client; ``backend("price_snapshot_store")`` or a SYNC Cosmos client (the price
  snapshot protocol is sync; the admin service always calls it through ``asyncio.to_thread``)
  closed with the composition.
* Publishes ``DOMAIN_REGISTRY`` (the identity routes reject an unregistered domain through it
  once the registry holds a domain).
* Startup hook: applies the stored review policy to the shared ``REVIEW_POLICIES`` registry the
  data builder published, once (no hot reload). A read failure keeps the defaults and logs a
  reason code only.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

from neurosphere_core.admin import (
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
)
from neurosphere_core.admin.platform import (
    BudgetAdmin,
    DomainAdmin,
    DomainRegistry,
    PlatformAdmin,
    PriceSheetAdmin,
    ReviewPolicyAdmin,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_core.clients.factories import ENV_COSMOS_ENDPOINT, ENV_COSMOS_KEY
from neurosphere_core.pricing import InMemoryPriceSnapshotStore, PriceSnapshotStore
from neurosphere_core.pricing.cosmos_store import CosmosPriceSnapshotStore

from neurosphere_api.admin.platform.service import PlatformAdminPlane, configure_admin_platform
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    DOMAIN_REGISTRY,
    REVIEW_POLICIES,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("admin_platform",)
_LOCAL_COSMOS_DEFAULT: Final = "https://127.0.0.1:8081"

_log = logging.getLogger("neurosphere_api.runtime")


def _in_memory(ctx: BuildContext) -> bool:
    return isinstance(ctx.overrides.policy_repository, InMemoryPolicyRepository)


def _repository(ctx: BuildContext) -> AdminConfigRepository:
    cloud = ctx.settings.cloud_profile.cloud.value
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return override
    if _in_memory(ctx):
        return InMemoryAdminConfigRepository(cloud=cloud)  # type: ignore[arg-type]
    return CosmosAdminConfigRepository.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        cloud=cloud,  # type: ignore[arg-type]
    )


def _sync_client(ctx: BuildContext) -> Any:
    """A sync Cosmos client for the price store (never used on the event loop)."""
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    if ctx.settings.env == "local":
        key = os.environ.get(ENV_COSMOS_KEY)
        if not key:
            raise ComponentUnavailableError("cosmos_key_missing")
        endpoint = os.environ.get(ENV_COSMOS_ENDPOINT, _LOCAL_COSMOS_DEFAULT)
        return CosmosClient(endpoint, key, enable_endpoint_discovery=False)
    account = ctx.store_settings().cosmos_account
    if not account:
        raise ComponentUnavailableError("cosmos_account_missing")
    profile = ctx.settings.cloud_profile
    return CosmosClient(
        profile.cosmos_endpoint(account), DefaultAzureCredential(authority=profile.login_host)
    )


def _price_store(ctx: BuildContext) -> PriceSnapshotStore:
    override = ctx.overrides.backend("price_snapshot_store")
    if override is not None:
        if not isinstance(override, PriceSnapshotStore):
            raise ComponentUnavailableError("price_snapshot_override_invalid")
        return override
    if _in_memory(ctx):
        return InMemoryPriceSnapshotStore()
    ctx.cosmos_client()  # same availability gate as every other Cosmos-backed component
    client = _sync_client(ctx)

    async def close() -> None:
        close_sync = getattr(client, "close", None)
        if callable(close_sync):
            close_sync()

    ctx.on_shutdown(close)
    return CosmosPriceSnapshotStore.from_client(client, database=ctx.store_settings().database)


def _plane(ctx: BuildContext) -> tuple[PlatformAdminPlane, DomainRegistry, AdminConfigRepository]:
    cloud = ctx.settings.cloud_profile.cloud.value
    repository = _repository(ctx)
    registry = DomainRegistry(repository)
    admin = PlatformAdmin(
        domains=DomainAdmin(repository, cloud=cloud),  # type: ignore[arg-type]
        registry=registry,
        budgets=BudgetAdmin(repository, registry),
        price_sheets=PriceSheetAdmin(
            _price_store(ctx),
            cloud=cloud,  # type: ignore[arg-type]
            allow_synthetic=ctx.settings.env == "local",
        ),
        review_policy=ReviewPolicyAdmin(repository),
    )
    plane = PlatformAdminPlane(admin=admin, audit=lambda: ctx.maybe_shared(AUDIT_REPOSITORY))
    return plane, registry, repository


def _load_review_policy(ctx: BuildContext, repository: AdminConfigRepository) -> None:
    registry = ctx.maybe_shared(REVIEW_POLICIES)
    try:
        customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    except ComponentUnavailableError:
        return
    if registry is None or customer is None:
        return

    async def load() -> None:
        try:
            applied = await registry.load_from(repository, customer)
        except Exception as exc:
            _log.warning(
                "stored review policy not loaded",
                extra={
                    "event": "admin_platform.review_policy_unloaded",
                    "error": type(exc).__name__,
                },
            )
            return
        _log.info(
            "review policy resolved",
            extra={"event": "admin_platform.review_policy_loaded", "stored": applied},
        )

    ctx.on_startup(load)


def build(ctx: BuildContext) -> None:
    configure_admin_platform(ctx.app, None)
    try:
        plane, registry, repository = _plane(ctx)
    except ComponentUnavailableError as exc:
        _log.warning("component admin_platform disabled: %s", exc.reason)
        ctx.disabled("admin_platform")
        return
    configure_admin_platform(ctx.app, plane)
    ctx.publish(DOMAIN_REGISTRY, registry)
    _load_review_policy(ctx, repository)
    ctx.ok("admin_platform")


BUILDER: Final = BuilderSpec("admin_platform", COMPONENTS, build)
