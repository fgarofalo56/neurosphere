# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from ...audit.v1 import audit_record
from . import detection_finding


class SecretFreeText(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=32768, min_length=0)]
    """
    Redacted text, 0 to 32768 characters, that matches none of the known credential formats (patterns are ECMA-262 compatible, no lookbehind). Mirrored by check_secret_free_text.
    """


class RedactedPart(BaseModel):
    """
    One redacted content part with its detection findings.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    part: detection_finding.ContentPartKind
    text: SecretFreeText
    truncated: StrictBool | None = False
    """
    True when the text was cut to the capture policy's max_part_chars.
    """
    findings: Annotated[
        list[detection_finding.DetectionFinding] | None,
        Field(max_length=256, validate_default=True),
    ] = []
    """
    Detector results for this part.
    """


class RedactedContent(BaseModel):
    """
    Redacted plaintext of one captured interaction (opt-in content capture, PRP-99): the document PRP-102 encrypts. It exists only in memory between redaction and encryption and after an audited decrypt; it is never an event, audit, index or notification field and no schema references it. Redaction replaces each detection with the placeholder `[[ns-redacted:<detected_category>]]`. Every text is secret-free: JSON Schema rejects text containing a private-key block, JWT, bearer token, AWS access key id, GitHub token, sk- key, Azure storage or Service Bus key assignment, SAS signature or URL with userinfo. The same patterns are mirrored by the Python validator check_secret_free_text in tests/contracts/validators.py, which PRP-101 must keep a subset of its credential detectors. redaction_state is `redacted` or `not_required` only; content whose redaction failed is not representable here. Pydantic ignores `not` (ADR-0004): validate against the JSON Schema before encryption.
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
    Interaction this content belongs to (lowercase UUID).
    """
    redaction_state: Literal["redacted", "not_required"]
    """
    `redacted`: detectors ran and replaced detections. `not_required`: detectors ran and found nothing to replace. No other state is storable.
    """
    detector_set_version: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._-]{0,63}$")]
    """
    Version of the deterministic detector set that produced this redaction.
    """
    parts: Annotated[list[RedactedPart], Field(max_length=5, min_length=1)]
    """
    One part per ContentPartKind, at most five.
    """
