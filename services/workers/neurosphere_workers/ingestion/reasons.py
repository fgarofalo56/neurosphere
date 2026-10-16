"""Closed set of quarantine reason codes (PRP-07 C3). The ONLY place reasons are defined.

Free-text failure reasons are never stored: a message can carry a prompt, and an exception
string can echo it. Every quarantine record carries exactly one of these codes.
"""

from __future__ import annotations

from enum import StrEnum


class QuarantineReason(StrEnum):
    INVALID_WIRE = "invalid_wire"  # not JSON, not a HubMessage, or wrong wire shape
    DEPTH_EXCEEDED = "depth_exceeded"  # JSON nesting over the shared limit (parser DoS)
    INVALID_SCHEMA = "invalid_schema"  # data violates the telemetry/cost contract
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"  # unknown major version or fields
    BODY_FIELD_PRESENT = "body_field_present"  # prompt/response field survived the edge
    CLOUD_MISMATCH = "cloud_mismatch"  # message cloud differs from this worker's cloud
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"  # sink kept failing transiently
