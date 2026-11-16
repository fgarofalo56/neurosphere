# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr

from . import control


class RepoPath(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=300, min_length=1)]


class SupportStatus(
    RootModel[
        Literal[
            "designed", "implemented_tested", "inherited", "customer", "planned", "not_applicable"
        ]
    ]
):
    root: Literal[
        "designed", "implemented_tested", "inherited", "customer", "planned", "not_applicable"
    ]


class EvidenceSourceId(
    RootModel[
        Literal[
            "catalog_ownership",
            "audit_chain",
            "hitl_decisions",
            "evaluation_results",
            "cost_attribution",
            "configuration_findings",
        ]
    ]
):
    root: Literal[
        "catalog_ownership",
        "audit_chain",
        "hitl_decisions",
        "evaluation_results",
        "cost_attribution",
        "configuration_findings",
    ]


class EvidenceSources(RootModel[list[EvidenceSourceId]]):
    root: Annotated[list[EvidenceSourceId], Field(max_length=6)]


class ControlMapping(BaseModel):
    """
    How NeuroSphere relates to one control (PRP-56). support_status reuses the PRP-23 vocabulary (designed, implemented_tested, inherited, customer, planned, not_applicable); evidence_sources names the read-only sources whose observations are relevant to the control. designed and implemented_tested support must cite repo_paths that exist (checked by the library loader). The mapping collects and maps; it never judges.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: control.SchemaVersion
    control_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,95}$")]
    framework_id: control.FrameworkId
    support_status: SupportStatus
    evidence_sources: EvidenceSources
    repo_paths: Annotated[list[RepoPath], Field(max_length=20)]
