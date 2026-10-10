# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class ValidationError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pointer: Annotated[StrictStr, Field(max_length=1024, pattern="^(/([^~/]|~[01])*)*$")]
    """
    RFC 6901 JSON Pointer into the request body.
    """
    detail: Annotated[StrictStr, Field(max_length=500, min_length=1)]
    """
    Human-readable failure; must not echo submitted values.
    """


class ProblemDetails(BaseModel):
    """
    Error response body for every NeuroSphere API, tool and MCP surface: an RFC 9457 problem details object profiled with the PRP.md section 3 taxonomy (code, retryable, correlation_id, optional reason, optional retry_after_seconds). Media type application/problem+json. The code -> status/retryable table is data in error-codes.json and is enforced here by allOf if/then. Rules JSON Schema cannot express are checked by Python validators in tests/contracts/test_error_taxonomy.py (PRP-01 item 7): test_error_table_matches_schema (error-codes.json and this allOf agree row for row) and, at runtime in PRP-05, the body status must equal the HTTP response status. detail and errors[].detail are human-readable and must never carry secrets, stack traces, query text or other tenants' data.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document (semver within major 1).
    """
    type: Annotated[StrictStr, Field(max_length=2048, min_length=1)]
    """
    RFC 9457 problem type, a URI reference. Use 'about:blank' or 'https://neurosphere.invalid/problems/<code>'. Never dereferenced by clients or tests.
    """
    title: Annotated[StrictStr, Field(max_length=200, min_length=1)]
    """
    RFC 9457 short, human-readable summary of the problem type; does not vary between occurrences.
    """
    status: Literal[401, 403, 409, 422, 429, 502, 503]
    """
    RFC 9457 HTTP status code. Fixed per code by the allOf below; must equal the HTTP response status.
    """
    detail: Annotated[StrictStr | None, Field(max_length=2000)] = None
    """
    RFC 9457 occurrence-specific human-readable explanation. No secrets, stack traces or query text.
    """
    instance: Annotated[StrictStr | None, Field(max_length=2048, min_length=1)] = None
    """
    RFC 9457 URI reference identifying this occurrence. Never dereferenced.
    """
    code: Literal[
        "unauthorized",
        "forbidden",
        "capability_unavailable",
        "stale_version",
        "rate_limited",
        "invalid_schema",
        "dependency_transient",
    ]
    """
    NeuroSphere error taxonomy code (PRP.md section 3).
    """
    retryable: StrictBool
    """
    Whether a client may retry the identical request automatically. Fixed per code.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    """
    Correlation ID shared with logs, traces and audit records for this request.
    """
    reason: Annotated[StrictStr | None, Field(pattern="^[a-z][a-z0-9_]{0,63}$")] = None
    """
    Machine-readable snake_case reason. Required for capability_unavailable (for example not_available_in_cloud, not_available_in_region, sku_unsupported, preview_only, outside_authorization_scope, disabled_by_policy); optional otherwise. Not free text.
    """
    retry_after_seconds: Annotated[StrictInt | None, Field(ge=1, le=86400)] = None
    """
    Seconds to wait before retrying; mirrors the Retry-After header. Required for rate_limited, optional for dependency_transient, forbidden when retryable is false.
    """
    errors: Annotated[list[ValidationError] | None, Field(max_length=100, min_length=1)] = None
    """
    invalid_schema only: per-member validation failures (RFC 9457 section 3 'errors' extension shape).
    """
