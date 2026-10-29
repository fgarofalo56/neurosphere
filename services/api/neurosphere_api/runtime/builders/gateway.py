"""Gateway plane builder (PRP-33 item 9): installs ``app.state.gateway_plane``.

``gateway_plane`` is OPTIONAL: a deployment that never registers a gateway still serves, and a
failure here is reported by reason code without touching any other component (the routes keep
answering 503 ``gateway_plane_unconfigured``).

* Store: ``NS_GATEWAY_STORE=memory`` (only under ``NS_ENV=local``) is in-memory; ``auto`` and
  ``cosmos`` (even under local) use the ``CosmosGatewayStore`` on the ONE shared Cosmos client
  (``ctx.cosmos_client()``) in the ``NS_STORE_DATABASE`` database, container
  ``NS_GATEWAY_COSMOS_CONTAINER`` (default ``gateways``). The container is in the
  ``neurosphere_core.stores`` registry: ``ensure_local_containers`` creates it under local and
  Bicep (``cosmos-containers.json``) elsewhere.
* ARM: ``neurosphere_core.clients.arm_client`` bound to the deployment cloud, with an aio
  ``DefaultAzureCredential`` (environment credential excluded outside local), closed at shutdown.
* Audit: the ``AUDIT_REPOSITORY`` the data builder published (the one the action plane audits to).

Test fakes: ``ctx.overrides.backend("gateway_store")`` (a ``GatewayStore``) and
``backend("gateway_arm_factory")`` (a ``Callable[[CloudProfile], httpx.AsyncClient]``).
"""

from __future__ import annotations

import logging
from typing import Final

import httpx
from azure.identity.aio import DefaultAzureCredential
from neurosphere_core.clients import arm_client
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.gateway import (
    CosmosGatewayStore,
    GatewayStore,
    InMemoryGatewayStore,
)
from pydantic import ValidationError

from neurosphere_api.gateway import GatewayPlane, GatewaySettings, configure_gateway_plane
from neurosphere_api.gateway.dependencies import ArmFactory
from neurosphere_api.gateway.settings import resolve_store_kind
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("gateway_plane",)

_log = logging.getLogger("neurosphere_api.runtime")


def _settings(ctx: BuildContext) -> GatewaySettings:
    try:
        return GatewaySettings.from_env(ctx.environ)
    except (ValidationError, InvalidSchemaError):
        raise ComponentUnavailableError("gateway_settings_invalid") from None


def _store(ctx: BuildContext, gateway: GatewaySettings) -> GatewayStore:
    override = ctx.overrides.backend("gateway_store")
    if override is not None:
        if not isinstance(override, GatewayStore):
            raise ComponentUnavailableError("gateway_store_override_invalid")
        return override
    try:
        kind = resolve_store_kind(ctx.settings, gateway)
    except InvalidSchemaError:
        raise ComponentUnavailableError("gateway_settings_invalid") from None
    if kind == "memory":
        return InMemoryGatewayStore()
    return CosmosGatewayStore.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        container=gateway.cosmos_container,
    )


def _arm_factory(ctx: BuildContext) -> ArmFactory:
    override = ctx.overrides.backend("gateway_arm_factory")
    if override is not None:
        if not callable(override):
            raise ComponentUnavailableError("gateway_arm_override_invalid")
        return override  # type: ignore[return-value]
    credential = DefaultAzureCredential(
        authority=ctx.settings.cloud_profile.login_host,
        exclude_environment_credential=ctx.settings.env != "local",
    )
    ctx.on_shutdown(credential.close)

    def factory(profile: CloudProfile) -> httpx.AsyncClient:
        return arm_client(profile, credential)

    return factory


def _install(ctx: BuildContext) -> None:
    gateway = _settings(ctx)
    audit = ctx.shared(AUDIT_REPOSITORY)
    store = _store(ctx, gateway)
    plane = GatewayPlane(store=store, audit=audit, arm_factory=_arm_factory(ctx), settings=gateway)
    configure_gateway_plane(ctx.app, plane)


def build(ctx: BuildContext) -> None:
    try:
        ctx.attempt("gateway_plane", lambda: _install(ctx))
    except Exception as exc:
        _log.error("gateway plane build raised %s", type(exc).__name__)
        ctx.failed("gateway_plane", "gateway_build_error")


BUILDER: Final = BuilderSpec("gateway", COMPONENTS, build)
