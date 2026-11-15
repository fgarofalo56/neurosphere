# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import (
    budget,
    common,
    connector_config,
    domain_definition,
    price_sheet_upload,
    producer_record,
    review_policy_document,
    system_setting,
)


class AdminConfigDocument(BaseModel):
    """
    Envelope of one versioned operator configuration document in the admin_config store (PRP-65). Partitioned by customer_id; one document per (kind, id), every accepted write increments version and replaces etag. A retired document is kept for audit and is never applied. body holds the kind's own contract document; JSON Schema validates it per kind (allOf below) and core validates it again through ADMIN_KIND_MODELS (PRP-65) because the generated Pydantic model cannot express the per-kind rule (ADR-0004 shape projection).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    id: common.RecordId
    """
    Document id, unique per customer and kind (for example the producer_id, domain slug or setting_key).
    """
    customer_id: common.CustomerId
    kind: common.AdminKind
    version: common.ConfigVersion
    etag: common.Etag
    status: Literal["active", "retired"]
    """
    active: applied by the runtime. retired: kept for audit and history only.
    """
    updated_at: common.Timestamp
    updated_by: common.PrincipalId
    """
    Pseudonymous principal that made the accepted write.
    """
    body: (
        producer_record.ProducerRecord
        | connector_config.ConnectorConfig
        | domain_definition.DomainDefinition
        | budget.SpendBudget
        | price_sheet_upload.PriceSheetUpload
        | review_policy_document.ReviewPolicyDocument
        | system_setting.SystemSetting
    )
    """
    The kind's contract document; allOf below pins which one. Never a credential value.
    """
