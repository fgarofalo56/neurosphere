# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class CredentialReference(BaseModel):
    """
    A reference to a credential, never the credential (A7). Either an Azure Key Vault secret identifier on the deployment's own cloud (vault.azure.net for Commercial, vault.usgovcloudapi.net for Government), resolved at runtime by managed identity, or the client id of a user-assigned managed identity. There is deliberately no member that can hold a secret value, connection string, SAS token or key. Rules JSON Schema cannot express (the vault host matches the cloud of the owning document) are checked by tests/contracts/validators.py::check_credential_reference_cloud.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["key_vault_secret", "managed_identity"]
    """
    key_vault_secret: secret_uri is required and managed_identity_client_id is absent. managed_identity: managed_identity_client_id is required and secret_uri is absent.
    """
    secret_uri: Annotated[
        StrictStr | None,
        Field(
            max_length=256,
            pattern="^https://[a-z][a-z0-9-]{1,22}[a-z0-9]\\.vault\\.(azure\\.net|usgovcloudapi\\.net)/secrets/[A-Za-z0-9-]{1,127}(/[0-9a-f]{32})?$",
        ),
    ] = None
    """
    Azure Key Vault secret identifier https://<vault>.vault.azure.net/secrets/<name>[/<version>] or the vault.usgovcloudapi.net equivalent. Same grammar as connectors/v1 credential_ref.vault_ref.
    """
    managed_identity_client_id: Annotated[
        StrictStr | None,
        Field(pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    ] = None
    """
    Client id (application id GUID, lowercase) of a user-assigned managed identity. An identifier, not a credential.
    """
