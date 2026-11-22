"""Settings the connector role builders use: the stored config when one exists, else the env.

``resolve_*_settings(cfg, lifetime)`` returns the existing settings class (so the role builders'
own checks run unchanged) or :data:`IDLE` markers:

* source ``env``, no stored record of the kind, or a store read failure -> the env-built settings,
  byte-identical to today's behaviour (a failure is one log line, never a startup failure);
* a stored config -> settings built from the stored fields only (stored wins, the environment does
  not leak in); the producer secret of ``gateway_poll`` and ``billing_export`` is read from Key
  Vault with the workload identity. A failed read raises
  ``RoleConfigError("connector_credential_unavailable")``;
* a stored config with ``enabled=false`` -> :class:`ConnectorIdle`; the role idles and does not
  fall back to the environment for that kind;
* source ``store`` with no stored record -> :class:`ConnectorIdle` as well.

A stored config that no longer passes the role's checks raises ``RoleConfigError`` with the same
reason code the API gave at creation time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.admin import AdminConfigRepository
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import InvalidSchemaError
from pydantic import SecretStr

from neurosphere_workers.connector_config import loader, stored
from neurosphere_workers.connector_config.idle import ConnectorIdle
from neurosphere_workers.connector_config.keyvault import (
    ConnectorCredentialUnavailableError,
    KeyVaultSecretReader,
    SecretReader,
    default_vault_token_provider,
)
from neurosphere_workers.connector_config.settings import ConnectorConfigSettings
from neurosphere_workers.ingestion.azure_monitor_ai.settings import AzureMonitorAiSettings
from neurosphere_workers.ingestion.billing_export import BillingExportSettings
from neurosphere_workers.ingestion.foundry_discovery import FoundryDiscoverySettings
from neurosphere_workers.ingestion.gateway_poll import GatewayPollSettings
from neurosphere_workers.runtime.roles import RoleConfigError

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = [
    "CREDENTIAL_UNAVAILABLE",
    "ConnectorIdle",
    "build_reader",
    "resolve_azure_monitor_ai_settings",
    "resolve_billing_export_settings",
    "resolve_foundry_discovery_settings",
    "resolve_gateway_poll_settings",
]

CREDENTIAL_UNAVAILABLE: Final = "connector_credential_unavailable"
_log = logging.getLogger("neurosphere_workers.connector_config")


def build_reader(cloud: CloudName, *, client_id: str | None, timeout: float) -> SecretReader:
    """The production Key Vault reader (tests replace this function)."""
    return KeyVaultSecretReader(
        cloud=cloud,
        token_provider=default_vault_token_provider(cloud, client_id=client_id),
        timeout_seconds=timeout,
    )


async def _stored(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    kind: str,
    repository: AdminConfigRepository | None,
) -> tuple[ConnectorConfig | ConnectorIdle | None, ConnectorConfigSettings]:
    """The stored config, an idle marker, or ``None`` meaning "use the environment"."""
    options = ConnectorConfigSettings()
    if options.source == "env":
        return None, options
    config: ConnectorConfig | None = None
    try:
        repo = repository or loader.open_repository(cfg, lifetime)
    except Exception:
        loader.log_store_unavailable(kind)
    else:
        config = await loader.load_stored_config(
            repo, cfg.customer_id, kind, timeout_seconds=options.timeout_seconds
        )
    if config is None:
        if options.source == "store":
            return ConnectorIdle(kind, "no_stored_config"), options
        return None, options
    if not config.enabled:
        _log.info(
            "stored connector config is disabled; role idles",
            extra={"event": "worker.connector_config_disabled", "connector_kind": kind},
        )
        return ConnectorIdle(kind, "disabled"), options
    return config, options


async def _secret(
    cfg: RuntimeConfig, config: ConnectorConfig, client_id: str | None, limit_seconds: float
) -> SecretStr:
    credential = config.credential
    if credential is None or credential.kind != "key_vault_secret":
        raise RoleConfigError(CREDENTIAL_UNAVAILABLE)
    reader = build_reader(CloudName(cfg.cloud), client_id=client_id, timeout=limit_seconds)
    try:
        return await reader.read(credential)
    except ConnectorCredentialUnavailableError:
        _log.warning(
            "connector credential unavailable",
            extra={
                "event": "worker.connector_credential_unavailable",
                "reason": CREDENTIAL_UNAVAILABLE,
                "connector_kind": config.connector_kind,
            },
        )
        raise RoleConfigError(CREDENTIAL_UNAVAILABLE) from None


def _invalid(exc: InvalidSchemaError) -> RoleConfigError:
    return RoleConfigError(exc.reason or "connector_config_invalid")


async def resolve_gateway_poll_settings(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    *,
    repository: AdminConfigRepository | None = None,
) -> GatewayPollSettings | ConnectorIdle:
    found, options = await _stored(cfg, lifetime, "gateway_poll", repository)
    if found is None:
        return GatewayPollSettings()
    if isinstance(found, ConnectorIdle):
        return found
    try:
        probe = stored.build_gateway_poll(found)
        secret = await _secret(
            cfg, found, probe.managed_identity_client_id, options.timeout_seconds
        )
        return stored.build_gateway_poll(found, secret=secret)
    except InvalidSchemaError as exc:
        raise _invalid(exc) from None


async def resolve_foundry_discovery_settings(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    *,
    repository: AdminConfigRepository | None = None,
) -> FoundryDiscoverySettings | ConnectorIdle:
    found, _options = await _stored(cfg, lifetime, "foundry_discovery", repository)
    if found is None:
        return FoundryDiscoverySettings()
    if isinstance(found, ConnectorIdle):
        return found
    try:
        return stored.build_foundry_discovery(found)
    except InvalidSchemaError as exc:
        raise _invalid(exc) from None


async def resolve_billing_export_settings(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    *,
    repository: AdminConfigRepository | None = None,
) -> BillingExportSettings | ConnectorIdle:
    found, options = await _stored(cfg, lifetime, "billing_export", repository)
    if found is None:
        return BillingExportSettings()
    if isinstance(found, ConnectorIdle):
        return found
    try:
        probe = stored.build_billing_export(found)
        secret = await _secret(
            cfg, found, probe.managed_identity_client_id, options.timeout_seconds
        )
        return stored.build_billing_export(found, secret=secret)
    except InvalidSchemaError as exc:
        raise _invalid(exc) from None


async def resolve_azure_monitor_ai_settings(
    cfg: RuntimeConfig,
    lifetime: ClientLifetime,
    *,
    repository: AdminConfigRepository | None = None,
) -> AzureMonitorAiSettings | ConnectorIdle:
    found, options = await _stored(cfg, lifetime, "azure_monitor_ai", repository)
    if found is None:
        return AzureMonitorAiSettings()
    if isinstance(found, ConnectorIdle):
        return found
    try:
        probe = stored.build_azure_monitor_ai(found)
        problem = stored.azure_monitor_ai_problem(probe, CloudName(cfg.cloud))
        if problem is not None:
            raise RoleConfigError(problem[1])
        secret = await _secret(
            cfg, found, probe.managed_identity_client_id, options.timeout_seconds
        )
        return stored.build_azure_monitor_ai(found, secret=secret)
    except InvalidSchemaError as exc:
        raise _invalid(exc) from None
