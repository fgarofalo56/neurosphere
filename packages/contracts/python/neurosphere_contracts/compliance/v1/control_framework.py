# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import control


class ControlFramework(BaseModel):
    """
    A versioned framework and the controls the library names for it (PRP-56). Held as data under neurosphere_core/compliance/library. Naming a framework here is not a claim that anything is supported or covered; use 'mapped controls' and 'evidence observed'.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: control.SchemaVersion
    framework_id: control.FrameworkId
    title: Annotated[StrictStr, Field(max_length=200, min_length=1)]
    framework_version: Annotated[StrictStr, Field(max_length=64, min_length=1)]
    source_url: Annotated[StrictStr, Field(pattern="^https://[^\\s]{1,500}$")]
    source_retrieved: Annotated[StrictStr, Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    controls: Annotated[list[control.Control], Field(max_length=200, min_length=1)]
