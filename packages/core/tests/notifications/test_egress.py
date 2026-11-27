"""Pure unit cases for the notification egress guard: host normalisation and reason codes."""

from __future__ import annotations

import pytest
from neurosphere_core.notifications.egress import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    REASON_CODES,
    RETRYABLE_REASON_CODES,
    EgressGuard,
    EgressRefusedError,
    EgressResponse,
    host_matches_entry,
    normalize_host,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("example.com.", "example.com"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("a-b.c0.io", "a-b.c0.io"),
    ],
)
def test_normalize_host(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        ".",
        ".example.com",
        "example..com",
        "-bad.example.com",
        "bad-.example.com",
        "under_score.example.com",
        "127.0.0.1",
        "::1",
        "a" * 64 + ".com",
        "exa mple.com",
        "example.com/",
    ],
)
def test_normalize_host_rejects(raw: str) -> None:
    assert normalize_host(raw) is None


@pytest.mark.parametrize(
    ("host", "entry", "matches"),
    [
        ("example.com", "example.com", True),
        ("hooks.example.com", "example.com", True),
        ("HOOKS.Example.com.", "example.com", True),
        ("evil-example.com", "example.com", False),
        ("example.com.evil.net", "example.com", False),
        ("notexample.com", "example.com", False),
        ("example.com", "hooks.example.com", False),
        ("com", "example.com", False),
        ("example.com", "", False),
    ],
)
def test_host_matches_entry_is_label_based(host: str, entry: str, matches: bool) -> None:
    assert host_matches_entry(host, entry) is matches


def test_defaults() -> None:
    guard = EgressGuard()
    assert guard.max_body_bytes == DEFAULT_MAX_BODY_BYTES == 64 * 1024
    assert guard.max_response_bytes == DEFAULT_MAX_RESPONSE_BYTES == 16 * 1024
    assert guard.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 10.0


@pytest.mark.parametrize("kwargs", [{"max_body_bytes": -1}, {"timeout_seconds": 0}])
def test_invalid_limits_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be"):
        EgressGuard(**kwargs)  # type: ignore[arg-type]


def test_reason_codes_stable() -> None:
    assert RETRYABLE_REASON_CODES <= REASON_CODES
    assert {"host_not_allowed", "blocked_address", "redirect", "timeout"} <= REASON_CODES


def test_refused_error_carries_only_id_and_reason() -> None:
    err = EgressRefusedError("redirect", "ops")
    assert (err.reason_code, err.channel_id) == ("redirect", "ops")
    assert str(err) == "notification egress refused for channel ops: redirect"


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (200, None, False),
        (503, "http_status", True),
        (429, "http_status", True),
        (400, "http_status", False),
        (302, "redirect", False),
        (None, "timeout", True),
        (None, "blocked_address", False),
    ],
)
def test_response_retryable(status: int | None, reason: str | None, retryable: bool) -> None:
    response = EgressResponse(status_code=status, reason_code=reason)  # type: ignore[arg-type]
    assert response.retryable is retryable
    assert response.ok is (reason is None)
