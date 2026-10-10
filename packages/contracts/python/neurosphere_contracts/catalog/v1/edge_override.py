# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictStr

from . import common


class SetConfidence(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = None


class EdgeOverride(BaseModel):
    """
    Steward decision on one edge (accept, reject, override, lock, unlock), applied with optimistic concurrency. The schema has no field that removes or replaces evidence_ids or security_evidence_ids, so an override cannot erase security evidence; observed facts are retained and the lock changes presented lineage only. lock and override decisions require a lock with locked=true, reason, expiry and actor. Python validators: validate_override_preserves_security_evidence, validate_customer_segment_matches, validate_override_relation_matches_edge (relation_type equals the type segment of edge_id), validate_lock_expiry_after_decision.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:edge_override:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Canonical ID of this immutable override decision. Canonical ID (canonical_id.schema.json) whose type segment is 'edge_override'.
    """
    edge_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:(invokes|delegates_to|uses_model|reads|writes|grounded_by|owned_by|depends_on|supersedes):[a-z0-9._/=-]+$",
        ),
    ]
    """
    Edge being curated. Canonical ID (canonical_id.schema.json) whose type segment is 'invokes' or 'delegates_to' or 'uses_model' or 'reads' or 'writes' or 'grounded_by' or 'owned_by' or 'depends_on' or 'supersedes'.
    """
    relation_type: common.RelationType
    expected_edge_version: common.EntityVersion
    expected_edge_etag: common.Etag
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    decision: Literal["accept", "reject", "override", "lock", "unlock"]
    actor: common.PersonId
    reason: Annotated[StrictStr, Field(max_length=2000, min_length=1)]
    decided_at: common.Timestamp
    lock: common.Lock | None = None
    set_confidence: SetConfidence | None = None
    set_validity: common.Validity | None = None
    add_evidence_ids: Annotated[
        list[common.EvidenceId] | None, Field(max_length=1000, validate_default=True)
    ] = []
    """
    Evidence appended by the steward. Evidence can be added, never removed.
    """
    review_item_id: common.EvidenceId | None = None
