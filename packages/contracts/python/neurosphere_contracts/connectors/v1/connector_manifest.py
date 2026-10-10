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


class Scope(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z][A-Za-z0-9._:/-]{0,255}$")]


class Granularity(BaseModel):
    """
    Finest grain of data the connector delivers.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    time_grain: Literal["event", "minute", "hour", "day", "month", "unknown"]
    subject_level: Literal["request", "principal", "agent", "deployment", "tenant", "unknown"]


class Freshness(BaseModel):
    """
    Expected delay between source event and availability, in integer milliseconds. null = unknown, never 0.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    typical_delay_ms: Annotated[StrictInt | None, Field(ge=0)]
    max_delay_ms: Annotated[StrictInt | None, Field(ge=0)]


class RateLimit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    limit_scope: Literal["per_connector", "per_tenant", "per_credential", "per_principal"]
    max_requests: Annotated[StrictInt, Field(ge=1)]
    window_ms: Annotated[StrictInt, Field(ge=1)]


class CredentialRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Logical credential name used by the connector code.
    """
    vault_ref: Annotated[
        StrictStr,
        Field(
            pattern="^https://[a-z][a-z0-9-]{1,22}[a-z0-9]\\.vault\\.(azure\\.net|usgovcloudapi\\.net)/secrets/[A-Za-z0-9-]{1,127}(/[0-9a-f]{32})?$"
        ),
    ]
    """
    Azure Key Vault secret identifier: https://<vault>.vault.azure.net/secrets/<name>[/<version>] or the vault.usgovcloudapi.net equivalent. Resolved at runtime by managed identity; the value never appears in a manifest, prompt or log.
    """


class WriteSupport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    supported: StrictBool
    actions: list[
        Literal[
            "model_deployment_swap",
            "model_deployment_scale",
            "policy_update",
            "routing_update",
            "agent_disable",
            "agent_enable",
        ]
    ]
    """
    Action kinds the connector can execute through the shared action executor. Empty when supported is false.
    """


class ConnectorManifest(BaseModel):
    """
    Registration manifest for one connector (NS-09): capabilities, permission scopes, data granularity, freshness, rate limits, credential references, advisory flag and write support. No member can hold a secret value: there is no free-text field, credentials are Key Vault secret identifiers (vault_ref) validated by pattern, and URLs cannot carry query strings, fragments or userinfo (so no SAS or signed URLs). Read-only connectors are advisory; only connectors with write support can back the action executor (PRP-17). Rules JSON Schema cannot express are checked by the Python validator check_connector_manifest in tests/contracts/test_connector_manifest.py (PRP-01 item 7): credential_refs names are unique; no pattern-constrained string (scopes, names) contains high-entropy or known secret-prefix material; a vault_ref host matches a cloud listed in supported_clouds (vault.azure.net for commercial, vault.usgovcloudapi.net for government).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    """
    Contract version of this document (semver within major 1).
    """
    name: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_-]{1,63}$")]
    """
    Connector identifier, lowercase.
    """
    version: Annotated[
        StrictStr,
        Field(
            pattern="^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]{1,64})?$"
        ),
    ]
    """
    Connector semantic version.
    """
    documentation_url: Annotated[
        StrictStr | None,
        Field(
            max_length=2048,
            pattern="^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~%/-]*)?$",
        ),
    ] = None
    """
    HTTPS documentation URL. No query string, fragment or userinfo.
    """
    supported_clouds: Annotated[list[Literal["commercial", "government"]], Field(min_length=1)]
    """
    Azure clouds this connector registration may run in. A registration never moves data between clouds.
    """
    capabilities: Annotated[
        list[
            Literal[
                "telemetry_ingest",
                "cost_ingest",
                "catalog_discovery",
                "usage_reports",
                "evaluation_results",
                "audit_events",
                "health_reporting",
                "action_execution",
            ]
        ],
        Field(min_length=1),
    ]
    """
    What the connector can provide or do.
    """
    scopes: Annotated[list[Scope], Field(max_length=64)]
    """
    Permission scopes or roles the connector requests (for example Reports.Read.All or https://management.azure.com/.default). Names only, never values.
    """
    granularity: Granularity
    """
    Finest grain of data the connector delivers.
    """
    freshness: Freshness
    """
    Expected delay between source event and availability, in integer milliseconds. null = unknown, never 0.
    """
    rate_limits: Annotated[list[RateLimit] | None, Field(max_length=16)]
    """
    Published source rate limits; null = unknown, empty array = source publishes none.
    """
    auth_mode: Literal["managed_identity", "workload_identity_federation", "vault_reference"]
    """
    managed_identity and workload_identity_federation carry no credential_refs; vault_reference requires at least one.
    """
    credential_refs: Annotated[list[CredentialRef], Field(max_length=8)]
    """
    Credentials by reference only. There is deliberately no field for a credential value.
    """
    advisory: StrictBool
    """
    true = recommendations from this connector are advisory only (no executable actions). Must be true exactly when write_support.supported is false.
    """
    write_support: WriteSupport
