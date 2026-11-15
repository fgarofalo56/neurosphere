# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import common


class ProducerSecretIssued(BaseModel):
    """
    OUTPUT-ONLY, SHOWN ONCE. Response to registering a producer or rotating its secret (PRP-41). secret is the only place in admin v1 where a credential value appears: it is generated server-side, returned once in this response, never stored (only secret_sha256 is) and can never be read back. It must not be logged, audited, cached or placed in a prompt; the audit record carries secret_sha256 only. No request schema may reference this schema.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    producer_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9_-]{1,128}$")]
    secret: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9_-]{43,128}$")]
    """
    Newly generated producer secret (URL-safe base64, at least 256 bits). Present the credential as Bearer <producer_id>.<secret>.
    """
    secret_sha256: Annotated[StrictStr, Field(pattern="^[0-9a-f]{64}$")]
    issued_at: common.Timestamp
    shown_once: Literal[True]
    """
    Always true: the secret cannot be retrieved again; rotate to get a new one.
    """
