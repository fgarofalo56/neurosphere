# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import control as control_1
from . import control_mapping, evidence_observation


class ControlSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    control: control_1.Control
    support_status: control_mapping.SupportStatus
    evidence_sources: control_mapping.EvidenceSources
    summary: Literal[
        "evidence_present", "evidence_partial", "no_evidence", "customer_responsibility"
    ]


class EvidenceBundle(BaseModel):
    """
    Deterministic, stateless evidence bundle for one domain and one framework (PRP-56). Per-control summary words (evidence_present, evidence_partial, no_evidence, customer_responsibility) derive only from observations and support status. There is no pass, fail, score or percentage. digest is sha256 over the canonical JSON of the bundle without the digest member. This bundle is not an assessment; not FedRAMP authorized; the authorizing official decides.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: control_1.SchemaVersion
    framework_id: control_1.FrameworkId
    framework_version: Annotated[StrictStr, Field(max_length=64, min_length=1)]
    library_version: Annotated[StrictStr, Field(max_length=64, min_length=1)]
    domain_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._-]+$",
        ),
    ]
    generated_at: evidence_observation.UtcTimestamp
    window_start: evidence_observation.UtcTimestamp
    window_end: evidence_observation.UtcTimestamp
    controls: Annotated[list[ControlSummary], Field(max_length=200)]
    observations: Annotated[list[evidence_observation.EvidenceObservation], Field(max_length=5)]
    digest: Annotated[StrictStr, Field(pattern="^sha256:[0-9a-f]{64}$")]
