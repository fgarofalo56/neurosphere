# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ...admin.v1 import common as common_1
from ...audit.v1 import audit_record
from ...catalog.v1 import common
from ...telemetry.v1 import telemetry_event
from . import detection_finding


class Model(BaseModel):
    """
    Model that served the interaction. Null when unknown.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    provider: common.Token | None
    """
    Provider token.
    """
    model_name: Annotated[StrictStr | None, Field(max_length=128, min_length=1)]
    """
    Model name as reported.
    """
    model_version: Annotated[StrictStr | None, Field(max_length=128, min_length=1)]
    """
    Model version as reported.
    """
    deployment_id: common.CanonicalId | None
    """
    Model deployment canonical id.
    """


class FindingsSummaryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    category: detection_finding.DetectedCategory
    """
    Detected category.
    """
    count: Annotated[StrictInt, Field(ge=1, le=100000)]
    action: Literal["replaced", "kept"]


class EncryptedObjectRef(BaseModel):
    """
    Reference to an AES-256-GCM encrypted object in content storage. The pointer is opaque and never fetched by schema validation; the wrapped data key lives in the blob header (PRP-102 decides). Only ciphertext is identified: no hash of plaintext.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    pointer: Annotated[StrictStr, Field(max_length=1024, min_length=1)]
    """
    Opaque storage pointer (blob path).
    """
    kek_uri: Annotated[
        StrictStr,
        Field(
            pattern="^https://[a-z0-9-]{3,24}\\.vault\\.(azure\\.net|usgovcloudapi\\.net)/keys/[A-Za-z0-9-]{1,127}(/[0-9a-f]{32})?$"
        ),
    ]
    """
    Key Vault key identifier of the key-encryption key that wraps the data key (https://<vault>.vault.azure.net or usgovcloudapi.net /keys/<name>[/<32 hex version>]). A key identifier only; the vault suffix must match the document's cloud (tests/contracts/validators.py check_kek_uri_cloud).
    """
    algorithm: Literal["aes_256_gcm"]
    """
    Content encryption algorithm.
    """
    ciphertext_sha256: Annotated[StrictStr, Field(pattern="^[a-f0-9]{64}$")]
    """
    SHA-256 of the ciphertext (lowercase hex), never of the plaintext.
    """
    byte_length: Annotated[StrictInt, Field(ge=1)]
    """
    Size of the encrypted object in bytes.
    """


class InteractionRecord(BaseModel):
    """
    Index document of one captured interaction (PRP-99; container interaction_index, declared by PRP-102). Metadata only: it has no content-bearing property, no string over 1024 characters, no hash of plaintext and references neither ContentEnvelope nor RedactedContent. The content lives encrypted behind content_ref (null when nothing was stored).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    interaction_id: audit_record.Uuid
    """
    Interaction identifier (lowercase UUID); joins payload_ref.interaction_id.
    """
    cloud: common.Cloud
    """
    Sovereign cloud boundary.
    """
    customer_id: common.CustomerId
    """
    Customer segment.
    """
    domain_id: common.DomainId
    """
    Owning domain; authorization scope anchor.
    """
    source_id: telemetry_event.Identifier
    """
    Connector or producer that emitted the event.
    """
    event_id: telemetry_event.Identifier
    """
    Source-assigned event id; with source_id it joins the TelemetryEvent.
    """
    trace_id: telemetry_event.TraceId | None = None
    """
    W3C trace id. Null when not traced.
    """
    span_id: telemetry_event.SpanId | None = None
    """
    Span id. Null when not reported.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]
    """
    Correlation id shared with the audit and policy trail.
    """
    capture_source: Literal["edge_push", "otlp_attributes", "gateway_log", "connector"]
    """
    How the interaction was captured: `edge_push`, `otlp_attributes`, `gateway_log` or `connector`. Open-ended: readers must tolerate unknown values.
    """
    occurred_at: common.Timestamp
    """
    When the interaction happened.
    """
    captured_at: common.Timestamp
    """
    When it was captured.
    """
    agent_id: common.CanonicalId | None = None
    """
    Agent canonical id. Null when not applicable.
    """
    agent_version_id: common.CanonicalId | None = None
    """
    Agent version canonical id. Null when not applicable.
    """
    tool_id: common.CanonicalId | None = None
    """
    Tool canonical id. Null when not applicable.
    """
    service_id: common.CanonicalId | None = None
    """
    Service canonical id. Null when not applicable.
    """
    mcp_server_id: common.CanonicalId | None = None
    """
    MCP server canonical id. Null when not applicable.
    """
    model: Model | None = None
    """
    Model that served the interaction. Null when unknown.
    """
    principal_id: common_1.PrincipalId | None = None
    """
    Pseudonymous principal. Null when unknown.
    """
    capture_policy_id: common_1.Slug
    """
    Capture policy that allowed the capture.
    """
    capture_policy_version: Annotated[StrictInt, Field(ge=1)]
    """
    Version of that capture policy.
    """
    detector_set_version: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Version of the deterministic detector set.
    """
    redaction_state: Literal["redacted", "not_required", "redaction_failed"]
    """
    `redacted`: detections replaced. `not_required`: nothing to replace. `redaction_failed`: nothing was stored (content_ref is null).
    """
    parts: telemetry_event.ContentParts
    """
    Which parts were captured and their sizes; sizes only, never text.
    """
    content_ref: EncryptedObjectRef | None
    """
    Encrypted content object. Null when nothing was stored.
    """
    findings_summary: Annotated[
        list[FindingsSummaryItem] | None, Field(max_length=64, validate_default=True)
    ] = []
    """
    Per category counts of detector findings; category names and counts only.
    """
    sensitivity_categories: common.SensitivityCategories | None = None
    """
    Sensitivity categories the interaction touched.
    """
    data_asset_ids: Annotated[
        list[common.CanonicalId] | None, Field(max_length=50, validate_default=True)
    ] = []
    """
    Data assets the interaction touched.
    """
    retention_class: Annotated[StrictStr | None, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")] = (
        "interaction_default"
    )
    """
    Retention class (slug).
    """
    expires_at: common.Timestamp
    """
    When the content expires (legal hold overrides).
    """
    legal_hold_ids: Annotated[
        list[common_1.RecordId] | None, Field(max_length=16, validate_default=True)
    ] = []
    """
    Legal holds on this interaction.
    """
