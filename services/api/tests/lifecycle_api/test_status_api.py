"""GET /api/v1/lifecycle/status: mode, policy state, queue depth."""

import json
from pathlib import Path
from typing import Any

from lifecycle_harness import ADMIN, VIEWER, make_env  # pyright: ignore[reportMissingImports]
from neurosphere_core.lifecycle.policy import load_policy_file

POLICY = {
    "policy_version": "records-2026-1",
    "retain_prompt_response_bodies": False,
    "rules": [{"data_class": "telemetry", "min_retention_days": 30, "max_retention_days": 365}],
}


def test_default_is_dry_run_with_no_policy() -> None:
    env = make_env()
    body: dict[str, Any] = env.call(ADMIN, "GET", "/status").json()
    assert body == {
        "mode": "dry_run",
        "policy_status": "unset",
        "policy_problem": "not_configured",
        "policy_version": None,
        "queue_depth": 0,
        "active_holds": 0,
    }


def test_execute_mode_is_reported_only_when_set() -> None:
    assert make_env(mode="execute").call(ADMIN, "GET", "/status").json()["mode"] == "execute"
    # Anything that is not exactly "execute" reads as the safe mode.
    assert make_env(mode="EXECUTE ").call(ADMIN, "GET", "/status").json()["mode"] == "dry_run"
    assert make_env(mode="").call(ADMIN, "GET", "/status").json()["mode"] == "dry_run"


def test_valid_policy_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(POLICY), encoding="utf-8")
    env = make_env(policy=load_policy_file(path))
    body = env.call(ADMIN, "GET", "/status").json()
    assert (body["policy_status"], body["policy_version"], body["policy_problem"]) == (
        "set",
        "records-2026-1",
        None,
    )


def test_invalid_policy_file_fails_closed_and_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, "rules": []}), encoding="utf-8")
    body = make_env(policy=load_policy_file(path)).call(ADMIN, "GET", "/status").json()
    assert (body["policy_status"], body["policy_problem"]) == ("unset", "invalid")
    missing = make_env(policy=load_policy_file(tmp_path / "absent.json"))
    assert missing.call(ADMIN, "GET", "/status").json()["policy_problem"] == "file_unreadable"


def test_queue_depth_and_holds_are_counted() -> None:
    env = make_env()
    env.call(
        ADMIN,
        "POST",
        "/requests",
        json={
            "action": "delete",
            "target": {"target_kind": "catalog", "container": "catalog", "record_id": "a"},
        },
    )
    env.call(ADMIN, "POST", "/holds", json={"reason_code": "audit", "subject_id": "s1"})
    body = env.call(ADMIN, "GET", "/status").json()
    assert (body["queue_depth"], body["active_holds"]) == (1, 1)


def test_status_needs_the_permission() -> None:
    assert make_env().call(VIEWER, "GET", "/status").status_code == 403


def test_every_lifecycle_route_is_declared_with_lifecycle_manage() -> None:
    from neurosphere_api.authz import route_inventory, undeclared_routes

    env = make_env()
    entries = [e for e in route_inventory(env.h.app) if e.path.startswith("/api/v1/lifecycle")]
    assert {(e.path, m) for e in entries for m in e.methods} == {
        ("/api/v1/lifecycle/holds", "POST"),
        ("/api/v1/lifecycle/holds", "GET"),
        ("/api/v1/lifecycle/holds/{hold_id}", "DELETE"),
        ("/api/v1/lifecycle/requests", "POST"),
        ("/api/v1/lifecycle/requests", "GET"),
        ("/api/v1/lifecycle/requests/{request_id}", "GET"),
        ("/api/v1/lifecycle/status", "GET"),
    }
    assert all(e.permissions == ("lifecycle.manage",) and not e.public for e in entries)
    assert not undeclared_routes(env.h.app)
