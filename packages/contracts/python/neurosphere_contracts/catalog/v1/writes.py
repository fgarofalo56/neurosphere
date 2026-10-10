# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr

from . import common


class WritesRelation(BaseModel):
    """
    WRITES relation. Source writes data to the target data asset. Every edge carries provenance, evidence_ids, confidence, first/last observation, validity interval, status and lock. Only curated edges may be locked; a curated edge carries its curation decision. Python validators: validate_canonical_id_fullmatch, validate_customer_segment_matches, validate_observation_order (first_observed <= last_observed), validate_validity_interval, validate_security_evidence_subset (security_evidence_ids is a subset of evidence_ids), validate_override_preserves_security_evidence (a new edge version keeps every prior security_evidence_ids entry), validate_lock_expiry_after_decision.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:writes:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Stable canonical ID of this edge. Canonical ID (canonical_id.schema.json) whose type segment is 'writes'.
    """
    relation_type: Literal["writes"]
    version: common.EntityVersion
    etag: common.Etag
    source_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:(agent|agent_version|tool|service):[a-z0-9._/=-]+$",
        ),
    ]
    """
    Edge source entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent' or 'agent_version' or 'tool' or 'service'.
    """
    target_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:(grounding_source|service):[a-z0-9._/=-]+$",
        ),
    ]
    """
    Edge target entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grounding_source' or 'service'.
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    provenance: common.Provenance
    evidence_ids: Annotated[list[common.EvidenceId], Field(max_length=1000)]
    """
    Evidence references; must be non-empty when status is inferred.
    """
    security_evidence_ids: Annotated[list[common.EvidenceId], Field(max_length=1000)]
    """
    Subset of evidence_ids that is security evidence. Overrides can never remove an entry (see edge_override.schema.json).
    """
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    first_observed: common.Timestamp
    last_observed: common.Timestamp
    validity: common.Validity
    status: common.RelationStatus
    lock: common.Lock
    curation: common.Curation | None = None
    created_at: common.Timestamp
    updated_at: common.Timestamp
    attributes: common.Attributes | None = None
