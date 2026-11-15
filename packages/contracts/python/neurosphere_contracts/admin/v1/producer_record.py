# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import common


class ProducerSource(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    source_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")]
    """
    Source identifier the producer publishes under (TelemetryEvent/CostRecord source_id).
    """
    observation_kind: Literal["gateway", "application", "billing"]


class ProducerRecord(BaseModel):
    """
    One registered ingest producer (PRP-41). Carries every field of the ingest edge's ProducerRegistration (services/api ingest/auth.py) so the registry can be loaded from the admin_config store: the producer authenticates with Authorization: Bearer <producer_id>.<secret> and the edge compares SHA-256(secret) with secret_sha256 in constant time. Only the hash is stored; the secret is returned once, in ProducerSecretIssued. A disabled producer is refused at the edge. Rules JSON Schema cannot express (source_id values are unique) are checked by tests/contracts/validators.py::check_producer_sources_unique.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    producer_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9_-]{1,128}$")]
    """
    Producer identifier, the part of the bearer credential before the dot. Same grammar as ProducerRegistration.producer_id.
    """
    customer_id: common.CustomerId
    cloud: common.Cloud
    sources: Annotated[list[ProducerSource], Field(max_length=64, min_length=1)]
    """
    Sources this producer may publish for, and how each source's data is observed (ProducerRegistration.sources).
    """
    secret_sha256: Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
    """
    Lowercase hex SHA-256 of the producer secret. A digest, never the secret.
    """
    status: Literal["active", "disabled"]
    rotated_at: common.Timestamp | None
    """
    When the current secret was issued (first issue or last rotation). Null for producers imported from a static registry file.
    """
