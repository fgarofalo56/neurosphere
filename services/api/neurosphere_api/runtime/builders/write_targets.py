"""Write-target settings and API composition (PRP-35 item 4; issue #132).

The API's ``WriteTargetRegistry`` holds the SAME connectors the executor worker registers, built
by the SAME code (``neurosphere_workers.runtime.factories.register_write_targets``) from the SAME
settings, so a dry run in the API plans against exactly what the worker would change. The API
only ever calls ``dry_run`` (``neurosphere_api.actions.dependencies``); apply, verify and rollback
happen in the executor worker. A real model swap therefore always goes through the action
executor, never through catalog metadata.

Settings (no secret in any of them; the credential is the workload identity through
``DefaultAzureCredential``, created only when a target is enabled and closed with the
composition lifetime):

=============================  ==============================================================
``NS_FOUNDRY_ENABLED``         ``true`` to register ``foundry-model-swap`` (default off)
``NS_FOUNDRY_SUBSCRIPTION_ID`` the Azure AI Services (Foundry) account's subscription (GUID)
``NS_FOUNDRY_RESOURCE_GROUP``  its resource group
``NS_FOUNDRY_ACCOUNT``         the account name
``NS_FOUNDRY_LOCATION``        its region (``eastus2``), for the Models - List read
``NS_APIM_ENABLED``            ``true`` to register ``apim-gateway`` (default off)
``NS_APIM_GATEWAY_ID``         the registered gateway's id (``gw-<32 hex>``)
``NS_APIM_DOMAIN_ID``          the domain the gateway is registered in
=============================  ==============================================================

The Foundry account's cloud is the deployment's ``NS_CLOUD``; the APIM gateway's cloud is its
registration's and must equal the deployment's. Government accounts/gateways, a missing
``deployments/write`` permission and anything else that yields the ADVISORY connector are
skipped with a logged reason code and never registered.

Limit: one connector per manifest name, so one Foundry account and one APIM gateway per
deployment (a second is skipped, ``write_target_duplicate``; first wins).

Timing: the Foundry factory reads ARM permissions and the APIM one reads the gateway registry, so
both run in a STARTUP hook (builders do no network I/O). The registry object installed on
``app.state`` is filled in place before the app serves. A failure there (ARM or the registry
unreachable) is logged by type and leaves that target out: its intents stay advisory in the API
(validation reports "no supported write connector"), never a pretend success.

Test seams (``ctx.overrides.backend``): ``write_target_seams`` (a ``WriteTargetSeams``: fake
credential, Foundry HTTP client, APIM ARM, APIM apply records) and ``gateway_store`` (the gateway
registry, same name the gateway builder honours). Without a ``gateway_store`` override the store
is the one the gateway builder installed (``app.state.gateway_plane.store``).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.gateway import (
    CosmosGatewayStore,
    GatewayRegistration,
    GatewayStore,
    InMemoryGatewayRecordStore,
)
from neurosphere_workers.actions.apim import ApplyRecord, ApplyRecords, apim_record_store
from neurosphere_workers.runtime.factories import (
    SUPPORTED_WRITE_CONNECTORS,
    WriteTargetSeams,
    WriteTargetSources,
    load_write_target_settings,
    register_write_targets,
)
from neurosphere_workers.runtime.settings import ApimWriteSettings, FoundryWriteSettings

from neurosphere_api.actions.dependencies import GATEWAY_PLANE_STATE
from neurosphere_api.runtime.builders import BuildContext, ComponentUnavailableError

__all__ = [
    "SUPPORTED_WRITE_CONNECTORS",
    "ApimWriteSettings",
    "FoundryWriteSettings",
    "WriteTargetSeams",
    "configure_write_targets",
]

_log = logging.getLogger("neurosphere_api.runtime")

_SEAMS: Final = "write_target_seams"
_GATEWAY_STORE: Final = "gateway_store"


def _seams(ctx: BuildContext) -> WriteTargetSeams | None:
    value = ctx.overrides.backend(_SEAMS)
    if value is None:
        return None
    if not isinstance(value, WriteTargetSeams):
        raise ComponentUnavailableError(f"{_SEAMS}_invalid")
    return value


def _gateway_store(ctx: BuildContext) -> GatewayStore | None:
    """The gateway registry: the override, else the gateway builder's (read at startup)."""
    override = ctx.overrides.backend(_GATEWAY_STORE)
    if isinstance(override, GatewayStore):
        return override
    plane: Any = getattr(ctx.app.state, GATEWAY_PLANE_STATE, None)
    store = getattr(plane, "store", None)
    return store if isinstance(store, GatewayStore) else None


def _records_for(ctx: BuildContext, store: GatewayStore | None) -> Any:
    """Apply records bound to the same place as ``store`` (as the executor worker writes them)."""

    def records_for(registration: GatewayRegistration) -> ApplyRecords:
        if isinstance(store, CosmosGatewayStore):
            plane: Any = getattr(ctx.app.state, GATEWAY_PLANE_STATE, None)
            container = getattr(getattr(plane, "settings", None), "cosmos_container", None)
            extra: dict[str, Any] = {} if not container else {"container": str(container)}
            return apim_record_store(
                ctx.cosmos_client(),
                database=ctx.store_settings().database,
                registration=registration,
                **extra,
            )
        return InMemoryGatewayRecordStore(ApplyRecord)

    return records_for


def configure_write_targets(ctx: BuildContext, registry: WriteTargetRegistry) -> None:
    """Fill ``registry`` at startup from ``NS_FOUNDRY_*``/``NS_APIM_*`` (module docstring).

    Nothing enabled: no hook, no credential, the registry stays empty. Malformed settings fail
    the caller's component (``write_target_settings_invalid``) at build time.
    """
    try:
        foundry, apim = load_write_target_settings()
    except ValueError:
        raise ComponentUnavailableError("write_target_settings_invalid") from None
    if not (foundry.enabled or apim.enabled):
        return
    seams = _seams(ctx)
    settings = ctx.settings
    lifetime = ctx.lifetime

    async def register() -> None:
        store = _gateway_store(ctx) if apim.enabled else None
        sources = WriteTargetSources(gateway_store=store, records_for=_records_for(ctx, store))
        try:
            customer = ctx.auth_settings().resolved_customer_id(settings.env)
        except ComponentUnavailableError:
            customer = None
        try:
            names = await register_write_targets(
                registry,
                settings=settings,
                customer_id=customer,
                lifetime=lifetime,
                foundry=foundry,
                apim=apim,
                sources=sources,
                seams=seams,
            )
        except Exception as exc:
            # Fail closed: the target stays out (intents advisory), the action plane still serves.
            _log.error("write target registration raised %s", type(exc).__name__)
            return
        _log.info("write targets registered: %s", ",".join(names) or "none")

    ctx.on_startup(register)
