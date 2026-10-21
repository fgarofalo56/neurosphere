"""Per-session budgets: message rate, subscriptions, sessions per principal, message size."""

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    HR,
    OPERATIONS,
    policy,
    role,
)
from neurosphere_api.realtime import RealtimeSettings
from neurosphere_api.realtime.budgets import TokenBucket
from neurosphere_core.auth.scope import Role

from .rt_helpers import build_rig, drain, until_pong

POLICIES = (policy(ALICE, role(Role.VIEWER, FINANCE, OPERATIONS, HR)),)


def test_message_rate_breach_returns_rate_limited_then_closes_4429() -> None:
    rig = build_rig(*POLICIES, message_burst=3, message_rate_per_second=1, max_rate_violations=2)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        for _ in range(3):
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "ping"})
        first = ws.receive_json()
        assert first["type"] == "error"
        assert first["code"] == "rate_limited"
        assert first["retry_after_seconds"] >= 1
        ws.send_json({"type": "ping"})
        messages, code = drain(ws)
    assert messages[0]["code"] == "rate_limited"
    assert code == 4429
    assert rig.registry.counters.rate_limited == 2


def test_the_rate_budget_refills_with_time() -> None:
    rig = build_rig(*POLICIES, message_burst=2, message_rate_per_second=1, max_rate_violations=5)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        for _ in range(2):
            ws.send_json({"type": "ping"})
            ws.receive_json()
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["code"] == "rate_limited"
        rig.h.clock.advance(5)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_subscription_budget_is_enforced_without_closing() -> None:
    rig = build_rig(*POLICIES, max_subscriptions=2)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        for domain in (FINANCE, OPERATIONS):
            ws.send_json({"type": "subscribe", "domain_id": domain})
            assert ws.receive_json()["type"] == "subscribed"
            assert ws.receive_json()["type"] == "delta"
        ws.send_json({"type": "subscribe", "domain_id": HR})
        refused = ws.receive_json()
        assert refused["type"] == "error"
        assert refused["code"] == "rate_limited"
        assert refused["reason"] == "subscription_limit"
        # Re-subscribing to an existing domain is not a new subscription.
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        assert ws.receive_json()["type"] == "subscribed"
        assert ws.receive_json()["type"] == "delta"  # a fresh snapshot of that domain
        # Unsubscribing frees a slot.
        ws.send_json({"type": "unsubscribe", "domain_id": OPERATIONS})
        assert ws.receive_json() == {"type": "unsubscribed", "domain_id": OPERATIONS}
        ws.send_json({"type": "subscribe", "domain_id": HR})
        assert ws.receive_json()["type"] == "subscribed"
        assert ws.receive_json()["type"] == "delta"


def test_sessions_per_principal_are_capped() -> None:
    rig = build_rig(*POLICIES, max_sessions_per_principal=1)
    with rig.client() as client, rig.connect(client, ALICE) as first:
        assert until_pong(first) == []
        with rig.connect(client, ALICE) as second:
            _, code = drain(second)
        assert code == 4429
        assert until_pong(first) == []  # the first session is unaffected
    assert rig.registry.session_count == 0


def test_oversized_messages_close_the_socket() -> None:
    rig = build_rig(*POLICIES, max_message_bytes=64)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        ws.send_text("x" * 65)
        messages, code = drain(ws)
    assert messages[0]["code"] == "invalid_schema"
    assert code == 1009


def test_binary_frames_are_refused() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json()["code"] == "invalid_schema"
        assert until_pong(ws) == []


def test_token_bucket_unit() -> None:
    now = [100.0]
    bucket = TokenBucket(2.0, 2, lambda: now[0])
    assert bucket.take() and bucket.take()
    assert not bucket.take()
    assert bucket.retry_after_seconds >= 1
    now[0] += 0.5
    assert bucket.take()
    assert not bucket.take()
    now[0] += 60
    assert bucket.take() and bucket.take() and not bucket.take()  # capped at burst


def test_token_bucket_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="positive"):
        TokenBucket(0, 1, lambda: 0.0)


def test_settings_read_ns_realtime_environment_and_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_REALTIME_MAX_SUBSCRIPTIONS", "3")
    monkeypatch.setenv("NS_REALTIME_POLL_INTERVAL_SECONDS", "1.5")
    settings = RealtimeSettings()
    assert settings.max_subscriptions == 3
    assert settings.poll_interval_seconds == 1.5
    assert RealtimeSettings().effective_refresh_seconds(10.0) == 1.0
    assert RealtimeSettings().effective_refresh_seconds(1.0) == 0.5
    monkeypatch.setenv("NS_REALTIME_MAX_SUBSCRIPTIONS", "0")
    with pytest.raises(ValueError, match="max_subscriptions"):
        RealtimeSettings()


def test_default_poll_interval_is_at_most_two_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_REALTIME_POLL_INTERVAL_SECONDS", raising=False)
    assert RealtimeSettings().poll_interval_seconds <= 2.0
