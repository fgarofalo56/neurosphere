"""PRP-40 item 4: ``GET /api/v1/audit/siem/status`` reports codes, never hosts or text."""

from __future__ import annotations

from datetime import UTC, datetime

from neurosphere_core.audit.siem_health import SiemSinkHealth

from .audit_api_helpers import AUDITOR_ALL, AUDITOR_FO, STEWARD, make_world

STATUS = "/api/v1/audit/siem/status"


def _at() -> datetime:
    return datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


def test_reports_sink_health_codes_only() -> None:
    w = make_world()
    health = SiemSinkHealth("eventhubs", clock=_at)
    health.record_success()
    health.record_failure("sink_auth_failed")
    health.record_failure("sink_unavailable")
    w.h.app.state.siem_sink_health = health
    response = w.get(AUDITOR_ALL, STATUS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "sink": "eventhubs",
        "state": "ok",
        "reason": None,
        "last_success_at": "2026-11-15T09:30:00Z",
        "last_failure_at": "2026-11-15T09:30:00Z",
        "consecutive_failures": 2,
        "total_failures": 2,
        "total_sent": 1,
        "last_failure_reason": "sink_unavailable",
    }
    assert "servicebus" not in response.text


def test_failed_configuration_is_reported() -> None:
    w = make_world()
    w.h.app.state.siem_sink_health = SiemSinkHealth(
        "eventhubs", state="failed", reason="audit_siem_settings_invalid"
    )
    body = w.get(AUDITOR_ALL, STATUS).json()
    assert (body["state"], body["reason"]) == ("failed", "audit_siem_settings_invalid")


def test_not_built_when_nothing_composed_the_sink() -> None:
    body = make_world().get(AUDITOR_ALL, STATUS).json()
    assert (body["sink"], body["state"]) == ("none", "not_built")


def test_domain_only_auditor_is_refused() -> None:
    response = make_world().get(AUDITOR_FO, STATUS)
    assert response.status_code == 403
    assert response.json()["reason"] == "customer_scope_required"


def test_non_auditor_is_refused() -> None:
    response = make_world().get(STEWARD, STATUS)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
