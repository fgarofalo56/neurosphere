# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)

from . import control, control_mapping


class Measure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    value: Annotated[StrictInt | None, Field(ge=0)]


class UtcTimestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?Z$"),
    ]


class EvidenceObservation(BaseModel):
    """
    What one read-only evidence source saw for a domain in a window (PRP-56). Counts, timestamps and ids only: no entity bodies, no prompts, no principal names. status: observed (the source answered), partial (answered with a cap or a gap), unavailable (store missing or down; reason_code says why), not_collected (the source cannot count this). Unknown numbers are null, never 0.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: control.SchemaVersion
    source_id: control_mapping.EvidenceSourceId
    status: Literal["observed", "partial", "unavailable", "not_collected"]
    reason_code: Annotated[StrictStr | None, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    snake_case machine reason; null when status is observed.
    """
    window_start: UtcTimestamp
    window_end: UtcTimestamp
    latest_at: UtcTimestamp | None
    """
    Newest timestamp the source saw; null when none or unknown.
    """
    truncated: StrictBool
    measures: Annotated[list[Measure], Field(max_length=20)]
