"""Connector configuration administration (PRP-42): credential references and the admin service."""

from neurosphere_core.admin.connectors.references import (
    KeyVaultSecretRef,
    check_credential_reference,
    key_vault_labels,
    parse_key_vault_secret,
)
from neurosphere_core.admin.connectors.service import (
    CONNECTOR_KIND,
    OBSERVATION_KINDS,
    ConnectorConfigAdmin,
    ConnectorKindValidator,
    ConnectorWrite,
    KindCheck,
)

__all__ = [
    "CONNECTOR_KIND",
    "OBSERVATION_KINDS",
    "ConnectorConfigAdmin",
    "ConnectorKindValidator",
    "ConnectorWrite",
    "KeyVaultSecretRef",
    "KindCheck",
    "check_credential_reference",
    "key_vault_labels",
    "parse_key_vault_secret",
]
