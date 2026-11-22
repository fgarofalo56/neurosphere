"""PRP-141 item 7: verify row 4 (Azure Monitor AI source) from a fake hosted API.

PASS needs an ``ok``/``partial`` run, events posted and a known dashboard point. Nothing here
contacts Azure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_verify_report import ENV, TOKEN_VALUE, FakeApi, states, verify


def _row(state: str, reason: str | None = None, **counts: int) -> dict[str, Any]:
    return {
        "kind": "azure_monitor_ai",
        "state": state,
        "reason": reason,
        "last_success_at": None,
        "last_attempt_at": None,
        "counts": counts,
    }


def _dash(points: int, status: str = "known") -> dict[str, Any]:
    pts = [{"t": f"t{i}", "value": {"value": 1.0, "status": status}} for i in range(points)]
    return {"series": [{"key": "k", "points": pts}] if pts else []}


def _api(row: dict[str, Any] | None, dash: dict[str, Any] | None = None) -> FakeApi:
    api = FakeApi(status=lambda: states())
    connectors = [] if row is None else [row]
    api.admin_status = (200, {"sources": [], "connectors": connectors})
    if dash is not None:
        api.dashboard = (200, dash)
    return api


def _monitor(tmp_path: Path, api: FakeApi) -> tuple[int, dict[str, Any]]:
    code, doc = verify(tmp_path, api)
    return code, doc["sources"]["azure_monitor"]


@pytest.mark.parametrize("state", ["ok", "partial"])
def test_ok_or_partial_with_events_and_visible_points_passes(tmp_path: Path, state: str) -> None:
    api = _api(_row(state, events_posted=7), _dash(3))
    _code, out = _monitor(tmp_path, api)
    assert out["result"] == "PASS" and out["reason"] == "events_visible"
    assert out["counts"] == {"events_posted": 7, "visible_series": 1, "visible_points": 3}
    assert api.bearers == {TOKEN_VALUE}


def test_ok_without_events_fails(tmp_path: Path) -> None:
    _code, out = _monitor(tmp_path, _api(_row("ok", events_posted=0), _dash(3)))
    assert out["result"] == "FAIL" and out["reason"] == "no_events"


def test_events_posted_but_nothing_visible_is_open_never_pass(tmp_path: Path) -> None:
    for dash in (_dash(0), _dash(2, status="unknown"), None):
        _code, out = _monitor(tmp_path, _api(_row("ok", events_posted=4), dash))
        assert out["result"] == "OPEN" and out["reason"] == "events_not_visible_yet"


@pytest.mark.parametrize(
    ("state", "reason", "expected"),
    [
        ("failed", "source_access_denied", "run_failed:source_access_denied"),
        ("idle", None, "run_idle"),
    ],
)
def test_failed_or_idle_run_fails_even_with_data(
    tmp_path: Path, state: str, reason: str | None, expected: str
) -> None:
    code, out = _monitor(tmp_path, _api(_row(state, reason, events_posted=9), _dash(5)))
    assert out["result"] == "FAIL" and out["reason"] == expected
    assert code == 1


def test_a_free_text_reason_is_not_copied_into_evidence(tmp_path: Path) -> None:
    api = _api(_row("failed", "Denied for fake.example.net 123", events_posted=0))
    _code, out = _monitor(tmp_path, api)
    assert out["reason"] == "run_failed"


@pytest.mark.parametrize("row", [None, _row("not_configured")])
def test_not_configured_is_open(tmp_path: Path, row: dict[str, Any] | None) -> None:
    code, out = _monitor(tmp_path, _api(row, _dash(3)))
    assert out["result"] == "OPEN" and out["reason"] == "not_configured"
    assert code == 0


def test_unreadable_admin_status_is_open(tmp_path: Path) -> None:
    api = FakeApi(status=lambda: states())  # admin status answers 404
    _code, out = _monitor(tmp_path, api)
    assert out["result"] == "OPEN" and out["reason"] == "status_unavailable"


def test_no_approval_is_refused_before_any_read(tmp_path: Path) -> None:
    api = _api(_row("ok", events_posted=1), _dash(1))
    env = {k: v for k, v in ENV.items() if k != "NS_LIVE_APPROVED"}
    code, doc = verify(tmp_path, api, env=env)
    assert code == 2 and doc == {} and api.urls == []


def test_evidence_holds_counts_only(tmp_path: Path) -> None:
    api = _api(_row("partial", "partial_results", events_posted=2), _dash(1))
    verify(tmp_path, api)
    text = (tmp_path / "ev" / "2026-11-21-verify.json").read_text(encoding="utf-8")
    assert "visible_points" in text and TOKEN_VALUE not in text and "fakecust" not in text
