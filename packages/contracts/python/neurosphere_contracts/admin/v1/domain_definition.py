# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from . import common


class DomainDefinition(BaseModel):
    """
    Operator definition of one domain (PRP-44): the authorization scope anchor every role, grant, connector and budget names. residency_region is the ARM region the domain's data is held in (Government domains use usgov*/usdod* regions; data is never bridged across clouds). The control domain is the reserved per-customer domain that holds platform configuration actions; at most one exists per customer (checked by the PRP-44 handler). A retired domain keeps its id for audit and accepts no new data.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    domain_id: common.DomainId
    display_name: common.DisplayName
    classification: Literal["public", "internal", "confidential", "restricted", "unknown"]
    """
    Data classification label (catalog/v1 classification vocabulary).
    """
    residency_region: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9]{1,31}$")]
    """
    Lowercase ARM region name (eastus2, usgovvirginia).
    """
    status: Literal["active", "retired"]
    is_control_domain: StrictBool
