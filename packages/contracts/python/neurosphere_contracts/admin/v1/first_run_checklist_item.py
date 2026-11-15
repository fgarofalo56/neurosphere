# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from . import common


class FirstRunChecklistItem(BaseModel):
    """
    OUTPUT-ONLY. One row of the operator first-run checklist (PRP-45): whether a platform component is configured, with a machine reason and a documentation path when it is not complete. complete carries no reason; every other status carries one, so the console can say why a component is missing, disabled or failing instead of showing a blank.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    item_id: common.Slug
    component: common.Slug
    """
    Runtime component the item checks (runtime status component name, for example cosmos, copilot, search).
    """
    status: Literal["complete", "missing", "disabled", "not_applicable", "error"]
    reason: common.ReasonCode | None
    doc_path: common.DocPath | None
    required: StrictBool
    """
    true when the platform cannot serve its core function without this component.
    """
