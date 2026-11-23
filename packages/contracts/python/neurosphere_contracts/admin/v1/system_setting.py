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
)

from . import common, credential_reference


class ModelEndpointSetting(BaseModel):
    """
    An Azure OpenAI / Foundry model deployment used by the copilot or the evaluation judge.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    endpoint: common.HttpsUrl
    deployment: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    """
    Model deployment name.
    """
    api_version: Annotated[StrictStr, Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}(-preview)?$")]
    resource_id: common.AzureResourceId | None
    credential: credential_reference.CredentialReference


class SearchSetting(BaseModel):
    """
    Azure AI Search service and index used for catalog and evidence search.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    endpoint: common.HttpsUrl
    index_name: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9-]{1,127}$")]
    resource_id: common.AzureResourceId | None
    credential: credential_reference.CredentialReference


class Scope(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^/subscriptions/[0-9a-fA-F-]{36}(/resourceGroups/[A-Za-z0-9._()-]{1,90})?$"),
    ]


class ScanSetting(BaseModel):
    """
    Scheduled discovery scan over the listed subscriptions or resource groups.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    interval_seconds: Annotated[StrictInt, Field(ge=300, le=604800)]
    scopes: Annotated[list[Scope], Field(max_length=64, min_length=1)]
    credential: credential_reference.CredentialReference


class McpServerSetting(BaseModel):
    """
    The NeuroSphere MCP server endpoint published to clients (PRP-22).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    endpoint: common.HttpsUrl
    resource_id: common.AzureResourceId | None
    credential: credential_reference.CredentialReference | None


class WriteTargetSetting(BaseModel):
    """
    Resource the action executor writes to (an API Management gateway or a Foundry project).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    target_kind: Literal["apim", "foundry"]
    resource_id: common.AzureResourceId
    credential: credential_reference.CredentialReference


class KekUri(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^https://[a-z0-9-]{3,24}\\.vault\\.(azure\\.net|usgovcloudapi\\.net)/keys/[A-Za-z0-9-]{1,127}(/[0-9a-f]{32})?$"
        ),
    ] = None
    """
    Key Vault key identifier of the key-encryption key; null only for local_development.
    """


class InteractionCaptureSetting(BaseModel):
    """
    Where captured interaction content is stored and how it is encrypted (PRP-99). kek_uri is a Key Vault key identifier only (https://<vault>.vault.azure.net or usgovcloudapi.net /keys/<name>[/<32 hex version>]); it is null only when kek_provider is local_development and is required when it is key_vault_key. The vault suffix must match the cloud of the deployment (tests/contracts/validators.py::check_kek_uri_cloud). Capture itself stays off until an approved capture_policy_change.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kek_provider: Literal["key_vault_key", "local_development"]
    """
    Where the key-encryption key lives. Open-ended: readers must tolerate unknown values.
    """
    kek_uri: KekUri | None
    """
    Key Vault key identifier of the key-encryption key; null only for local_development.
    """
    content_storage_account_resource_id: common.AzureResourceId
    content_container: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")]
    credential: credential_reference.CredentialReference
    max_content_chars_per_interaction: Annotated[StrictInt | None, Field(ge=1, le=163840)] = 65536
    shed_capture_at_queue_percent: Annotated[StrictInt | None, Field(ge=1, le=100)] = 80


class EgressAllowedHost(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=253,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
        ),
    ]


class NotificationsSetting(BaseModel):
    """
    Notification sender limits and the egress allow-list (PRP-99). Hostnames only; every channel's allowed_host must be on this list at send time.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    egress_allowed_hosts: Annotated[list[EgressAllowedHost], Field(max_length=32, min_length=1)]
    max_attempts: Annotated[StrictInt | None, Field(ge=1, le=20)] = 8
    retry_base_seconds: Annotated[StrictInt | None, Field(ge=1, le=3600)] = 30
    dedup_window_seconds: Annotated[StrictInt | None, Field(ge=0, le=86400)] = 900


class EnforcementSetting(BaseModel):
    """
    Policy decision service limits (PRP-99). The SDK guard fails open by default (owner decision GD-8); enforcement modes live on EnforcementBinding and default to audit.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    decision_cache_ttl_seconds: Annotated[StrictInt | None, Field(ge=0, le=3600)] = 60
    sdk_failure_mode: Literal["fail_open", "fail_closed"] | None = "fail_open"
    """
    Open-ended: readers must tolerate unknown values.
    """
    decide_rate_limit_per_minute: Annotated[StrictInt | None, Field(ge=1, le=60000)] = 600


class SystemSetting(BaseModel):
    """
    One runtime setting the operator manages from the console instead of environment variables (PRP-45). setting_key selects which typed member is present: exactly the member named by setting_key is set and no other. Each member holds endpoints, Azure resource ids and a CredentialReference only, never a key, token or connection string. enabled false keeps the configuration but disables the component (the first-run checklist reports it as disabled). Core validates the per-key rule again (ADMIN_KIND_MODELS, PRP-65) because the generated Pydantic model carries every member as optional.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    setting_key: Literal[
        "copilot",
        "judge",
        "search",
        "scan",
        "mcp_server",
        "write_target",
        "interaction_capture",
        "notifications",
        "enforcement",
    ]
    """
    Open-ended: readers must tolerate unknown values.
    """
    enabled: StrictBool
    copilot: ModelEndpointSetting | None = None
    judge: ModelEndpointSetting | None = None
    search: SearchSetting | None = None
    scan: ScanSetting | None = None
    mcp_server: McpServerSetting | None = None
    write_target: WriteTargetSetting | None = None
    interaction_capture: InteractionCaptureSetting | None = None
    notifications: NotificationsSetting | None = None
    enforcement: EnforcementSetting | None = None
