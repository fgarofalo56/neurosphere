# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from . import common, credential_reference


class Settings(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=512)]


class ConnectorConfig(BaseModel):
    """
    Operator configuration of one connector instance (PRP-42): which connector, which domains it reports into, its bounded scalar settings and the credential it uses, by reference only. settings refuses nested objects, arrays and secret-like keys (secret, password, token, key, sas, signature, credential, connection); a credential is never a setting. Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_connector_config_cloud: every domain_id is on one cloud and a key_vault_secret credential names a vault on that cloud (check_credential_reference_cloud).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    connector_id: common.Slug
    """
    Operator-chosen id of this connector instance, unique per customer.
    """
    connector_kind: Literal[
        "gateway_poll", "foundry_discovery", "billing_export", "otel", "azure_monitor_ai"
    ]
    domain_ids: Annotated[list[common.DomainId], Field(max_length=64, min_length=1)]
    """
    Domains the connector's data is attributed to. At least one; no wildcard.
    """
    settings: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$", strict=True)],
        Settings | StrictInt | StrictBool,
    ]
    """
    Bounded scalar settings for the connector kind (poll interval, resource ids, endpoints). Values are strings up to 512 characters, integers or booleans; nothing nested.
    """
    credential: credential_reference.CredentialReference | None
    """
    Credential by reference (Key Vault secret or managed identity). Null when the connector needs none (for example an OTLP receiver behind the producer credential).
    """
    enabled: StrictBool
