# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from . import detection_finding, interaction_access_purpose, interaction_record


class Filters(BaseModel):
    """
    Selection filters.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    from_: Annotated[common.Timestamp, Field(alias="from")]
    """
    Start of the window.
    """
    to: common.Timestamp
    """
    End of the window.
    """
    agent_ids: Annotated[list[common.CanonicalId], Field(max_length=64)]
    detected_categories: Annotated[list[detection_finding.DetectedCategory], Field(max_length=32)]


class InteractionExportManifest(BaseModel):
    """
    Manifest of one interaction content export (PRP-99). Metadata only: ids, counts, the purpose and an encrypted bundle reference; no content. Written by PRP-104.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    export_id: audit_record.Uuid
    """
    Export identifier (lowercase UUID).
    """
    cloud: common.Cloud
    """
    Sovereign cloud boundary.
    """
    customer_id: common.CustomerId
    """
    Customer segment.
    """
    domain_ids: Annotated[list[common.DomainId], Field(max_length=64, min_length=1)]
    """
    Domains the export draws from.
    """
    requested_by: common_1.PrincipalId
    """
    Requesting principal (pseudonym).
    """
    requested_at: common.Timestamp
    """
    When requested.
    """
    purpose: interaction_access_purpose.InteractionAccessPurpose
    """
    Why the export was requested.
    """
    filters: Filters
    """
    Selection filters.
    """
    interaction_count: Annotated[StrictInt, Field(ge=0)]
    """
    Interactions in the bundle.
    """
    interaction_ids: Annotated[list[audit_record.Uuid], Field(max_length=1000)]
    """
    Interactions in the bundle.
    """
    excluded_count: Annotated[StrictInt, Field(ge=0)]
    """
    Interactions excluded (no permission, expired or held).
    """
    includes_held_content: StrictBool
    """
    Whether content under legal hold is included.
    """
    bundle: interaction_record.EncryptedObjectRef
    """
    Encrypted export bundle.
    """
    audit_id: audit_record.Uuid
    """
    Audit record of the export.
    """
    expires_at: common.Timestamp
    """
    When the bundle expires.
    """
