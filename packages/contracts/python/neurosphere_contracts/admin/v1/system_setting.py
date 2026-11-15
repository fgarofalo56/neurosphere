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


class SystemSetting(BaseModel):
    """
    One runtime setting the operator manages from the console instead of environment variables (PRP-45). setting_key selects which typed member is present: exactly the member named by setting_key is set and no other. Each member holds endpoints, Azure resource ids and a CredentialReference only, never a key, token or connection string. enabled false keeps the configuration but disables the component (the first-run checklist reports it as disabled). Core validates the per-key rule again (ADMIN_KIND_MODELS, PRP-65) because the generated Pydantic model carries every member as optional.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    setting_key: Literal["copilot", "judge", "search", "scan", "mcp_server", "write_target"]
    enabled: StrictBool
    copilot: ModelEndpointSetting | None = None
    judge: ModelEndpointSetting | None = None
    search: SearchSetting | None = None
    scan: ScanSetting | None = None
    mcp_server: McpServerSetting | None = None
    write_target: WriteTargetSetting | None = None
