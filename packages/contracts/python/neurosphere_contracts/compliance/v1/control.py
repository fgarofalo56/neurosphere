# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr


class SchemaVersion(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]


class FrameworkId(
    RootModel[Literal["nist_ai_rmf", "sr_11_7", "hipaa_technical_safeguards", "omb_m_25_21"]]
):
    root: Literal["nist_ai_rmf", "sr_11_7", "hipaa_technical_safeguards", "omb_m_25_21"]


class Control(BaseModel):
    """
    One control of an external framework held as library data (PRP-56). Metadata only: a short paraphrased title and a link to the official source, never copied text. A control record says what the framework names; it never says whether anyone meets it.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: SchemaVersion
    control_id: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,95}$")]
    """
    Stable NeuroSphere control id (lowercase, dot separated). Other PRPs cite it.
    """
    framework_id: FrameworkId
    title: Annotated[StrictStr, Field(max_length=200, min_length=1)]
    source_url: Annotated[StrictStr, Field(pattern="^https://[^\\s]{1,500}$")]
    source_retrieved: Annotated[StrictStr, Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    """
    Date the control id and title were read from the official source.
    """
    framework_version: Annotated[StrictStr, Field(max_length=64, min_length=1)]
