"""Connector configuration for the worker roles (PRP-42).

An admin stores a ``ConnectorConfig`` (credential by reference only) through the admin API; the
connector roles read it here at startup, stored winning over the environment per connector kind.
``validators.VALIDATORS`` is what the API runs at creation time so a config the worker would
refuse is never saved. See ``docs/runbooks/connector-config.md``.
"""

from neurosphere_workers.connector_config.idle import ConnectorIdle
from neurosphere_workers.connector_config.keyvault import (
    ConnectorCredentialUnavailableError,
    KeyVaultSecretReader,
)
from neurosphere_workers.connector_config.loader import load_stored_config
from neurosphere_workers.connector_config.resolve import (
    resolve_azure_monitor_ai_settings,
    resolve_billing_export_settings,
    resolve_foundry_discovery_settings,
    resolve_gateway_poll_settings,
)
from neurosphere_workers.connector_config.settings import ConnectorConfigSettings
from neurosphere_workers.connector_config.validators import VALIDATORS

__all__ = [
    "VALIDATORS",
    "ConnectorConfigSettings",
    "ConnectorCredentialUnavailableError",
    "ConnectorIdle",
    "KeyVaultSecretReader",
    "load_stored_config",
    "resolve_azure_monitor_ai_settings",
    "resolve_billing_export_settings",
    "resolve_foundry_discovery_settings",
    "resolve_gateway_poll_settings",
]
