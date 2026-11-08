"""The live catalog latency mode refuses without operator approval (runs in CI, no Azure)."""

from __future__ import annotations

from .live_guard import (
    ENV_APPROVED,
    ENV_DATABASE,
    ENV_ENDPOINT,
    NOT_APPROVED_REASON,
    live_refusal,
)


def test_refuses_without_approval_even_when_configured() -> None:
    env = {ENV_ENDPOINT: "https://example.invalid:443/", ENV_DATABASE: "db"}
    assert live_refusal(env) == NOT_APPROVED_REASON
    assert live_refusal({**env, ENV_APPROVED: "0"}) == NOT_APPROVED_REASON
    assert live_refusal({**env, ENV_APPROVED: "true"}) == NOT_APPROVED_REASON
    assert "OPEN" in NOT_APPROVED_REASON


def test_approved_but_unconfigured_still_refuses() -> None:
    reason = live_refusal({ENV_APPROVED: "1"})
    assert reason is not None
    assert ENV_ENDPOINT in reason
    reason = live_refusal({ENV_APPROVED: "1", ENV_ENDPOINT: "https://example.invalid:443/"})
    assert reason is not None
    assert ENV_DATABASE in reason


def test_approved_and_configured_proceeds() -> None:
    env = {ENV_APPROVED: "1", ENV_ENDPOINT: "https://example.invalid:443/", ENV_DATABASE: "db"}
    assert live_refusal(env) is None
