"""PRP-27 item 2: the render entry point refuses to run without a complete approval."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
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


def test_template_with_todo_fields_is_refused(tmp_path: Path) -> None:
    rows = ["| Field | Value |", "|---|---|"]
    rows += [f"| {name} | TODO(operator) |" for name in rv.REQUIRED_FIELDS]
    path = tmp_path / "template.md"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(rv.GuardError, match="TODO"):
        rv.parse_approval(path)
    assert rv.run(rv.StubBackend(), approval_path=path, out_dir=tmp_path) != 0


def test_shipped_approval_is_complete() -> None:
    assert rv.parse_approval(rv.APPROVAL_PATH).budget > 0


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


def _fake_runner(calls: list[list[str]]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        out = "4.0\n" if cmd[0] == "ffprobe" else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    return run


def test_local_backend_requires_live_flag(tmp_path: Path) -> None:
    path = _approval(tmp_path / "a.md")
    backend = rv.LocalBackend(tmp_path / "out", runner=_fake_runner([]))
    assert rv.run(backend, approval_path=path, out_dir=tmp_path, env={}) != 0
    assert not (tmp_path / "out").exists()


def test_local_backend_scene_uses_measured_duration_at_zero_cost(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    backend = rv.LocalBackend(tmp_path, runner=_fake_runner(calls))
    for folder in (backend.frames, backend.audio, backend.clips):
        folder.mkdir(parents=True)
    backend.shots = {"S01": ["S01_1.png", "S01_2.png"]}
    scene = rv.Scene("S01", "Opening", "Hello there.", 11.0)
    assert backend.render_scene(scene) == Decimal("0.00")
    assert [c[0] for c in calls] == ["powershell", "ffprobe", "ffmpeg"]
    assert backend.measured == {"S01": 4.0}
    (measured,) = backend.measured_scenes([scene])
    assert measured.duration_s == 4.0 + rv.PAUSE_SECONDS
    vtt = rv.build_vtt([measured])
    assert "00:00:00.000 --> 00:00:04.000" in vtt
    assert "Hello there." in vtt


def test_stub_cli_does_not_touch_real_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rv.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
    before = rv.SPEND_LOG_PATH.read_bytes() if rv.SPEND_LOG_PATH.exists() else None
    assert rv.main(["--backend", "stub"]) == 0
    assert (tmp_path / "captions.vtt").is_file()
    assert (tmp_path / "spend-log.md").is_file()
    after = rv.SPEND_LOG_PATH.read_bytes() if rv.SPEND_LOG_PATH.exists() else None
    assert before == after


def test_tracker_never_exceeds_cap(tmp_path: Path) -> None:
    tracker = rv.SpendTracker(tmp_path / "s.md", Decimal(5), "USD")
    tracker.charge("a", Decimal(5))
    with pytest.raises(rv.BudgetExceededError):
        tracker.charge("b", Decimal("0.01"))
    assert tracker.total == Decimal(5)
