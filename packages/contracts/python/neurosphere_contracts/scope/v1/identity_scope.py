# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
    """


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix required).
    """


class CanonicalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern so this schema has no cross-area dependency.
    """


class Principal(BaseModel):
    """
    Pseudonymous principal (PRP-01 clarification 8). No name, email or other direct identifier.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    principal_id: CanonicalId
    principal_pseudonym: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,127}$")]
    """
    Stable pseudonym; re-identification is a policy-store concern, not a contract field.
    """
    principal_kind: Literal["user", "service_principal", "managed_identity", "agent"]


class RoleAssignment(BaseModel):
    """
    One role bound to explicit domains (NS-08 roles). Privileged roles (admin, security_auditor) must carry expires_at: privileged access is scoped and time-bound. expires_at > derived_at is checked by tests/contracts/validators.py::check_identity_scope_times.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    role: Literal["viewer", "analyst", "domain_steward", "admin", "security_auditor"]
    domain_ids: Annotated[list[CanonicalId], Field(max_length=1024, min_length=1)]
    """
    Domains this role applies to. At least one; there is no tenant-wide form.
    """
    expires_at: Timestamp | None = None


class ResourceGrant(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    resource_id: CanonicalId
    permissions: Annotated[
        list[Literal["read", "export", "propose_action", "approve", "execute"]],
        Field(min_length=1),
    ]
    expires_at: Timestamp | None = None


class IdentityScope(BaseModel):
    """
    OUTPUT-ONLY. The server-derived authorization scope of one principal, computed from a validated identity token and the current policy store. It is never accepted from a caller or a model: no request schema may $ref this schema (asserted by tests/contracts/test_scope_isolation.py), and caller- or model-supplied domain_id/customer_id values are ignored for authorization. The same object is passed to REST, graph, analytics, search, cache keys, exports, WebSocket, copilot tools and MCP. There is deliberately no wildcard, all-domains or bypass field: privileged roles are scoped to explicit domains and time-bound. scope_hash correctness (sha256 over the canonical JSON of cloud, customer_id, principal.principal_id, roles, allowed_domains, allowed_resources and policy_version, keys sorted, no whitespace) cannot be expressed in JSON Schema and is checked by tests/contracts/validators.py::check_identity_scope_hash. expires_at > derived_at is checked by tests/contracts/validators.py::check_identity_scope_times.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    cloud: Literal["commercial", "government"]
    """
    The single cloud this scope is valid in. A scope never spans commercial and government.
    """
    customer_id: Annotated[StrictStr, Field(pattern="^[a-z0-9._-]{1,128}$")]
    """
    Customer segment of the canonical ID grammar, taken from the validated token's tenant mapping, never from request input.
    """
    principal: Principal
    roles: Annotated[list[RoleAssignment], Field(max_length=64)]
    allowed_domains: Annotated[list[CanonicalId], Field(max_length=1024)]
    """
    Explicit canonical Domain IDs the principal may read. Empty means no domain access. No wildcard form exists.
    """
    allowed_resources: Annotated[list[ResourceGrant], Field(max_length=4096)]
    """
    Resource-scoped grants (custom resource-scoped permissions, NS-08) outside or narrower than domain grants.
    """
    policy_version: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._+-]{1,64}$")]
    """
    Version of the policy store snapshot the scope was derived from; a newer policy version invalidates cached scopes.
    """
    derived_at: Timestamp
    expires_at: Timestamp | None = None
    """
    Optional cache expiry for this derived scope. Absent means the server's default scope TTL applies.
    """
    scope_hash: Annotated[StrictStr, Field(pattern="^sha256:[0-9a-f]{64}$")]
    """
    sha256 over the canonical JSON of the scope-defining fields (see schema description). Used in cache keys and audit records.
    """
