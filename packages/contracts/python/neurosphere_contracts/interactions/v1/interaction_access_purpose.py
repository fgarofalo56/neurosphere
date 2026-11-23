# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...admin.v1 import common


class InteractionAccessPurpose(BaseModel):
    """
    Why content is read or exported (PRP-99). A fragment (no schema_version) embedded by access requests and InteractionExportManifest. A code plus an optional case reference, never prose (audit content_guard forbids it).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    purpose_code: Literal[
        "incident_investigation",
        "policy_violation_review",
        "legal_hold_review",
        "data_subject_request",
        "security_review",
        "quality_review",
    ]
    """
    Purpose of the access; open-ended: readers must tolerate unknown values.
    """
    case_ref: common.RecordId | None
    """
    Case record id (admin record_id). Null when none.
    """
