# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import common


class Alias(BaseModel):
    """
    Alias document mapping an alias (external agent ID, label, previous ID) to one canonical ID; resolves collisions and agent aliases. Python validators: validate_canonical_id_fullmatch, validate_customer_segment_matches, validate_alias_type_matches (entity_type equals the type segment of canonical_id), validate_alias_unique (one active alias per (alias_source_id, alias_kind, alias_value)).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:alias:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical ID of this alias document. Canonical ID (canonical_id.schema.json) whose type segment is 'alias'.
    """
    version: common.EntityVersion
    etag: common.Etag
    created_at: common.Timestamp
    updated_at: common.Timestamp
    cloud: common.Cloud
    customer_id: common.CustomerId
    alias_value: Annotated[
        StrictStr,
        Field(max_length=512, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$"),
    ]
    """
    Source-native identifier or label that resolves to canonical_id.
    """
    alias_kind: Literal["external_id", "display_name", "previous_canonical_id", "source_native_id"]
    alias_source_id: common.Token
    """
    Source in which alias_value is valid.
    """
    canonical_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Target canonical ID. Person aliases are forbidden: mapping a real identifier to a pseudonym is re-identification data and lives in the policy store.
    """
    entity_type: Literal[
        "agent",
        "agent_version",
        "model_deployment",
        "grounding_source",
        "tool",
        "service",
        "domain",
        "owner",
        "policy",
        "recommendation",
        "run_reference",
    ]
    status: Literal["active", "retired"]
    validity: common.Validity
    provenance: common.Provenance
