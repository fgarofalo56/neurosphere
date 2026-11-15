"""The retention policy file: unset, valid, unreadable and invalid all fail closed."""

from __future__ import annotations

import json
from pathlib import Path

from neurosphere_core.lifecycle import UNSET
from neurosphere_core.lifecycle.policy import load_policy_file

from .lifecycle_helpers import POLICY_RAW


def test_no_path_is_unset() -> None:
    assert load_policy_file(None) == UNSET
    assert load_policy_file("") == UNSET
    assert load_policy_file("   ") == UNSET


def test_valid_file_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(POLICY_RAW), encoding="utf-8")
    state = load_policy_file(path)
    assert state.status == "set"
    assert state.policy is not None
    assert state.policy.policy_version == "records-2026-1"


def test_missing_file_fails_closed_to_unset(tmp_path: Path) -> None:
    state = load_policy_file(tmp_path / "absent.json")
    assert (state.status, state.problem) == ("unset", "file_unreadable")


def test_not_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_policy_file(path).problem == "file_unreadable"


def test_json_that_is_not_an_object_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_policy_file(path).problem == "invalid"


def test_invalid_policy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY_RAW, "rules": []}), encoding="utf-8")
    state = load_policy_file(path)
    assert (state.status, state.problem) == ("unset", "invalid")
    assert state.policy is None
