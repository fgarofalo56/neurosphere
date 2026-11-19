# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr

from . import (
    agent,
    agent_version,
    common,
    domain,
    grant,
    grounding_source,
    mcp_server,
    model_deployment,
    owner,
    person,
    policy,
    recommendation_reference,
    run_reference,
    service,
    tool,
)


class ChangedField(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]


class ChangeReason(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=500, min_length=1)] = None


class AuditId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    ] = None
    """
    Audit record that logged the change (lowercase UUID); null when none exists, for example a projection.
    """


class CorrelationId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")] = None


class EntityRevision(BaseModel):
    """
    One immutable, retained revision of a catalog entity (PRP-70; the revision store and writer are PRP-76). revision_id is '<entity canonical id>@<entity_version>'; JSON Schema checks only that it is a canonical id followed by '@' and a positive integer, and core must also check that the id and version equal entity_id and entity_version (documented for PRP-76). body holds the full entity document as it was at that version; JSON Schema pins it to the schema named by entity_type (allOf below, the AdminConfigDocument precedent) and the generated Pydantic model cannot express that pin (ADR-0004 shape projection), so core validates body again against the entity's own model. body_sha256 is a 'sha256:' digest of body; the canonical serialization the digest covers is defined by the revision writer (PRP-76), not by this contract, which fixes the shape only. Nullable members are optional and default to null, as on the catalog entities. Python validators: check_revision_version_order (previous_version < entity_version when previous_version is not null).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    revision_id: Annotated[
        StrictStr,
        Field(
            max_length=640,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+@[1-9][0-9]*$",
        ),
    ]
    """
    '<entity canonical id>@<entity_version>', unique per entity and version.
    """
    entity_id: common.CanonicalId
    entity_type: common.EntityType
    entity_version: common.EntityVersion
    """
    The entity's own version recorded by this revision.
    """
    previous_version: common.EntityVersion | None = None
    """
    Entity version this revision replaced; null for the first revision or when the history starts here.
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    operation: Literal[
        "create", "update", "deprecate", "recertify", "retire", "import", "projection"
    ]
    recorded_at: common.Timestamp
    recorded_by: common.PersonId | None = None
    """
    Pseudonymous person id that made the change; null for workers and connectors.
    """
    changed_fields: Annotated[list[ChangedField], Field(max_length=64)]
    """
    Top-level property names of the entity that differ from the previous revision.
    """
    change_reason: ChangeReason | None = None
    audit_id: AuditId | None = None
    """
    Audit record that logged the change (lowercase UUID); null when none exists, for example a projection.
    """
    correlation_id: CorrelationId | None = None
    body_sha256: Annotated[StrictStr, Field(pattern="^sha256:[a-f0-9]{64}$")]
    """
    Digest of body; shape only, the serialization it covers is defined by the revision writer (PRP-76).
    """
    body: (
        person.Person
        | agent.Agent
        | agent_version.AgentVersion
        | model_deployment.ModelDeployment
        | grounding_source.GroundingSource
        | tool.Tool
        | service.Service
        | domain.Domain
        | owner.Owner
        | policy.Policy
        | recommendation_reference.RecommendationReference
        | run_reference.RunReference
        | grant.Grant
        | mcp_server.McpServer
    )
    """
    The full entity document at entity_version; allOf below pins which entity schema it must satisfy. Never a credential value.
    """
