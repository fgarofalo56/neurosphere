"""PRP-27 item 2: captions match the storyboard narration and the transcript passes lint.

Tolerance: cue text must equal the storyboard narration after whitespace normalisation
(ratio 1.0, tolerance 0). The storyboard 'Caption' lines are hand-shortened on purpose, so
at least CAPTION_MIN_COVERAGE of their words must appear in the narration of the same
scene. The script.md narration must equal the storyboard narration.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_PATH = ROOT / "marketing" / "video" / "render" / "render_video.py"
_SPEC = importlib.util.spec_from_file_location("render_video", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
rv = importlib.util.module_from_spec(_SPEC)
sys.modules["render_video"] = rv
_SPEC.loader.exec_module(rv)

CAPTION_MIN_COVERAGE = 0.65


def _norm(text: str) -> str:
    return " ".join(text.split())


def _vtt_cues(vtt: str) -> dict[str, str]:
    cues: dict[str, str] = {}
    for block in vtt.split("\n\n")[1:]:
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            cues[lines[0]] = _norm(" ".join(lines[2:]))
    return cues


def test_vtt_matches_narration() -> None:
    scenes = rv.parse_scenes()
    vtt = rv.build_vtt(scenes)
    assert vtt.startswith("WEBVTT")
    cues = _vtt_cues(vtt)
    assert set(cues) == {s.scene_id for s in scenes}
    for scene in scenes:
        assert cues[scene.scene_id] == _norm(scene.narration)


def test_vtt_timestamps_are_ordered() -> None:
    vtt = rv.build_vtt(rv.parse_scenes())
    stamps = re.findall(r"(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})", vtt)
    assert len(stamps) == len(rv.parse_scenes())
    previous = "00:00:00.000"
    for start, end in stamps:
        assert previous <= start < end
        previous = end


def test_script_matches_storyboard_narration() -> None:
    script = rv.parse_script()
    for scene in rv.parse_scenes():
        assert script[scene.scene_id] == _norm(scene.narration)


def test_storyboard_caption_lines_close_to_narration() -> None:
    text = rv.STORYBOARD_PATH.read_text(encoding="utf-8")
    captions = re.findall(r"^- Caption: (.+)$", text, flags=re.MULTILINE)
    scenes = rv.parse_scenes()
    assert len(captions) == len(scenes)
    for caption, scene in zip(captions, scenes, strict=True):
        words = re.findall(r"[a-z0-9-]+", caption.lower())
        vocab = set(re.findall(r"[a-z0-9-]+", scene.narration.lower()))
        coverage = sum(w in vocab for w in words) / len(words)
        assert coverage >= CAPTION_MIN_COVERAGE, scene.scene_id


def test_transcript_passes_claims_lint() -> None:
    assert rv.lint_transcript(rv.transcript(rv.parse_scenes())) == []
