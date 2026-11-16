"""The API's stored-settings snapshot: loaded ONCE per process before the builders run (PRP-45).

Builders do no network I/O; this read is the single exception, made with a bounded timeout from
``compose_app`` (and from the scan bootstrap, which runs first in ``main.create`` and shares the
process cache, so both see the same values). Sources:

* production (``compose_app`` without overrides): a short-lived Cosmos client on its own event
  loop (``run_blocking``) reads ``admin_config`` for the bound customer and is closed again. No
  customer binding or no Cosmos configuration is ``unconfigured``; a timeout or failure is
  ``unavailable`` (``stored_settings_unavailable``). Either way the builders use env (A5).
* tests: ``backend("stored_settings")`` (a prebuilt snapshot) or
  ``backend("admin_config_repository")`` (read through the same loader); any other override set
  is ``unconfigured`` so no test ever reaches a real store.

``STORED_SETTINGS`` publishes the snapshot to the builders (``ctx.maybe_shared``); ``None`` there
means "env only". :func:`setting_source` tells the status route whether a key's applied value came
from the store, the environment or the defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Literal

from neurosphere_core.admin import AdminConfigRepository, CosmosAdminConfigRepository
from neurosphere_core.admin.runtime import (
    DEFAULT_LOAD_TIMEOUT_SECONDS,
    PROCESS_CACHE,
    STORED_SETTINGS_UNCONFIGURED,
    SettingKey,
    StoredSettingsSnapshot,
    load_stored_settings,
    run_blocking,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.clients.factories import ENV_COSMOS_ENDPOINT, ENV_COSMOS_KEY
from neurosphere_core.cloud import Settings
from pydantic import ValidationError

from neurosphere_api.runtime.builders import SharedKey
from neurosphere_api.runtime.settings import AuthSettings, StoreSettings

if TYPE_CHECKING:
    from neurosphere_api.runtime.overrides import CompositionOverrides

__all__ = [
    "ENV_PREFIXES",
    "STORED_SETTINGS",
    "SettingSource",
    "load_from_settings",
    "setting_source",
    "snapshot_for_composition",
]

STORED_SETTINGS: Final[SharedKey[StoredSettingsSnapshot]] = SharedKey("stored_settings")

SettingSource = Literal["stored", "env", "default"]

#: Environment variable prefixes that configure each key when nothing is stored.
ENV_PREFIXES: Final[Mapping[str, tuple[str, ...]]] = {
    "copilot": ("NS_COPILOT_",),
    "judge": ("NS_WORKER_EVAL_JUDGE",),
    "search": ("NS_SEARCH_",),
    "scan": ("NS_SCAN_",),
    "mcp_server": ("NS_MCP_",),
    "write_targets": ("NS_FOUNDRY_", "NS_APIM_"),
}


def _unconfigured() -> StoredSettingsSnapshot:
    return StoredSettingsSnapshot.empty("unconfigured", STORED_SETTINGS_UNCONFIGURED)


def _customer(settings: Settings) -> str | None:
    try:
        return AuthSettings().resolved_customer_id(settings.env)
    except ValidationError:
        return None


def _cloud(settings: Settings) -> Literal["commercial", "government"]:
    return settings.cloud_profile.cloud.value  # type: ignore[return-value]


def load_from_settings(
    settings: Settings, *, limit_seconds: float = DEFAULT_LOAD_TIMEOUT_SECONDS
) -> StoredSettingsSnapshot:
    """The production read (see module doc); cached per process and deployment."""
    customer = _customer(settings)
    try:
        store = StoreSettings()
    except ValidationError:
        return _unconfigured()
    if customer is None:
        return _unconfigured()
    if settings.env == "local":
        if not os.environ.get(ENV_COSMOS_KEY):
            return _unconfigured()
    elif not store.cosmos_account:
        return _unconfigured()
    cloud = _cloud(settings)
    cache_key = (
        "api",
        settings.env,
        cloud,
        customer,
        store.database,
        store.cosmos_account,
        os.environ.get(ENV_COSMOS_ENDPOINT),
    )

    async def load() -> StoredSettingsSnapshot:
        lifetime = ClientLifetime()
        try:
            client = create_cosmos_client(settings, lifetime=lifetime, account=store.cosmos_account)
            repository = CosmosAdminConfigRepository.from_client(
                client, database=store.database, cloud=cloud
            )
            return await load_stored_settings(
                repository, customer, cloud=cloud, limit_seconds=limit_seconds
            )
        finally:
            await lifetime.aclose()

    return PROCESS_CACHE.get_or_load(
        cache_key, lambda: run_blocking(load, limit_seconds=limit_seconds)
    )


def snapshot_for_composition(
    settings: Settings, overrides: CompositionOverrides | None
) -> StoredSettingsSnapshot:
    """What ``compose_app`` hands the builders (see module doc)."""
    if overrides is None:
        return load_from_settings(settings)
    prebuilt = overrides.backend("stored_settings")
    if isinstance(prebuilt, StoredSettingsSnapshot):
        return prebuilt
    repository = overrides.backend("admin_config_repository")
    customer = _customer(settings)
    if not isinstance(repository, AdminConfigRepository) or customer is None:
        return _unconfigured()
    cloud = _cloud(settings)

    async def load() -> StoredSettingsSnapshot:
        return await load_stored_settings(repository, customer, cloud=cloud)

    return run_blocking(load)


def env_configures(key: SettingKey, environ: Mapping[str, str]) -> bool:
    prefixes = ENV_PREFIXES[key]
    return any(n.upper().startswith(prefixes) and v.strip() for n, v in environ.items())


def setting_source(
    key: SettingKey, snapshot: StoredSettingsSnapshot, environ: Mapping[str, str] | None = None
) -> SettingSource:
    """``stored`` when the applied snapshot holds a valid value, else ``env`` or ``default``."""
    if snapshot.has(key):
        return "stored"
    return "env" if env_configures(key, os.environ if environ is None else environ) else "default"
