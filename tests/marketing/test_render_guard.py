"""PRP-27 item 2: the render entry point refuses to run without a complete approval."""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_PATH = ROOT / "marketing" / "video" / "render" / "render_video.py"
_SPEC = importlib.util.spec_from_file_location("render_video", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
rv = importlib.util.module_from_spec(_SPEC)
sys.modules["render_video"] = rv
_SPEC.loader.exec_module(rv)


def _approval(path: Path, budget: str = "100", overrides: dict[str, str] | None = None) -> Path:
    values = {name: "synthetic value" for name in rv.REQUIRED_FIELDS}
    values["Budget amount"] = budget
    values["Currency"] = "USD"
    values.update(overrides or {})
    rows = ["| Field | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in values.items()]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_missing_file_exits_nonzero(tmp_path: Path) -> None:
    code = rv.run(rv.StubBackend(), approval_path=tmp_path / "nope.md", out_dir=tmp_path)
    assert code != 0


def test_shipped_template_is_refused() -> None:
    with pytest.raises(rv.GuardError, match="TODO"):
        rv.parse_approval(rv.APPROVAL_PATH)


def test_malformed_file_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("no table here\n", encoding="utf-8")
    with pytest.raises(rv.GuardError, match="malformed"):
        rv.parse_approval(path)


@pytest.mark.parametrize("value", ["TODO(operator)", ""])
def test_todo_or_empty_field_refused(tmp_path: Path, value: str) -> None:
    path = _approval(tmp_path / "a.md", overrides={"Approver": value})
    with pytest.raises(rv.GuardError, match="Approver"):
        rv.parse_approval(path)
    assert rv.run(rv.StubBackend(), approval_path=path, out_dir=tmp_path) != 0


def test_complete_approval_passes_guard(tmp_path: Path) -> None:
    path = _approval(tmp_path / "a.md", budget="1,250.50")
    approval = rv.parse_approval(path)
    assert approval.budget == Decimal("1250.50")
    assert approval.currency == "USD"
    code = rv.run(
        rv.StubBackend(), approval_path=path, out_dir=tmp_path, spend_log=tmp_path / "spend.md"
    )
    assert code == 0
    assert (tmp_path / "captions.vtt").read_text(encoding="utf-8").startswith("WEBVTT")


def test_non_stub_requires_live_flag(tmp_path: Path) -> None:
    path = _approval(tmp_path / "a.md")
    code = rv.run(rv.RealBackend(), approval_path=path, out_dir=tmp_path, env={})
    assert code != 0
    with pytest.raises(rv.GuardError, match="NS_LIVE_APPROVED"):
        rv.check_live_gate("real", {})
    rv.check_live_gate("real", {"NS_LIVE_APPROVED": "1"})
    rv.check_live_gate("stub", {})


def test_real_backend_is_placeholder(tmp_path: Path) -> None:
    path = _approval(tmp_path / "a.md")
    code = rv.run(
        rv.RealBackend(),
        approval_path=path,
        out_dir=tmp_path,
        spend_log=tmp_path / "s.md",
        env={"NS_LIVE_APPROVED": "1"},
    )
    assert code != 0
    with pytest.raises(NotImplementedError, match="operator"):
        rv.RealBackend().render_scene(rv.parse_scenes()[0])


def test_stops_at_budget_cap_and_log_appends(tmp_path: Path) -> None:
    path = _approval(tmp_path / "a.md", budget="25")
    log = tmp_path / "spend.md"
    log.write_text("| existing row |\n", encoding="utf-8")
    backend = rv.StubBackend(cost_per_scene=Decimal(10))
    code = rv.run(backend, approval_path=path, out_dir=tmp_path, spend_log=log)
    assert code != 0
    assert len(backend.rendered) == 3  # third scene is rendered, its charge is refused
    text = log.read_text(encoding="utf-8")
    assert text.startswith("| existing row |\n")
    assert "REFUSED (cap)" in text
    assert text.count("| ok |") == 2


def test_tracker_never_exceeds_cap(tmp_path: Path) -> None:
    tracker = rv.SpendTracker(tmp_path / "s.md", Decimal(5), "USD")
    tracker.charge("a", Decimal(5))
    with pytest.raises(rv.BudgetExceededError):
        tracker.charge("b", Decimal("0.01"))
    assert tracker.total == Decimal(5)
