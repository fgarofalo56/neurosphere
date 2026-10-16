"""Closed set of ingest reason codes (the ``reason`` of an error or a per-item outcome)."""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    # Whole-request failures: invalid_schema (422).
    BODY_TOO_LARGE = "body_too_large"
    DEPTH_EXCEEDED = "depth_exceeded"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    INVALID_ENVELOPE = "invalid_envelope"
    # Whole-request failures: forbidden (403).
    CLAIM_MISMATCH = "claim_mismatch"
    CLOUD_MISMATCH = "cloud_mismatch"
    # Whole-request failure: rate_limited (429).
    RATE_LIMITED = "rate_limited"
    # Per-item rejections.
    INVALID_EVENT = "invalid_event"
    MISSING_TIME = "missing_time"
    INVALID_TRACE_ID = "invalid_trace_id"
    INVALID_METRIC_VALUE = "invalid_metric_value"
    INVALID_CLOUDEVENT = "invalid_cloudevent"
    UNSUPPORTED_EVENT_TYPE = "unsupported_event_type"
    # Per-item "ignored": valid input that the documented subset does not map.
    UNSUPPORTED_METRIC_TYPE = "unsupported_metric_type"
    UNMAPPED_METRIC_NAME = "unmapped_metric_name"
    UNSUPPORTED_TEMPORALITY = "unsupported_temporality"
