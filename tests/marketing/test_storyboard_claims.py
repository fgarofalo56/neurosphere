"""PRP-26 item 3: the explainer video storyboard is source only and its claims hold up."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
STORY_DIR = ROOT / "marketing" / "video" / "storyboard"
STORYBOARD = STORY_DIR / "storyboard.md"
SCRIPT = STORY_DIR / "script.md"
CLAIMS = STORY_DIR / "claims.md"
RULES_PATH = ROOT / "tests" / "marketing" / "claims_rules.py"

SOURCE_FILES = (STORYBOARD, SCRIPT, CLAIMS)
MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".mkv",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".srt",
    ".vtt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
}
SCENE_FIELDS = ("Visual", "Narration", "On-screen text", "Caption", "Claims", "Sources")

# Fallback banned phrases, each with a regex. A hit is ignored inside a negation.
FALLBACK_BANNED = {
    "authorized": re.compile(r"\bauthorized\b", re.I),
    "ATO": re.compile(r"\bATO\b"),
    "FedRAMP compliant": re.compile(r"fedramp[- ]compliant", re.I),
    "parity": re.compile(r"\bparity\b", re.I),
    "unique": re.compile(r"\bunique(ly)?\b", re.I),
    "guaranteed": re.compile(r"\bguaranteed?\b", re.I),
    "saves N percent": re.compile(r"\bsaves?\s+(up to\s+)?\d+\s*(%|percent)", re.I),
}
NEGATION = re.compile(
    r"\b(no|not|never|nor|without|neither|isn't|aren't|makes no claim)\b|"
    r"\bnone of\b|\bauthorization\b",
    re.I,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _front_matter(text: str) -> dict[str, object]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "missing front matter"
    data: dict[str, object] = {}
    key = None
    for line in match.group(1).splitlines():
        item = re.match(r"\s+-\s+(.*)", line)
        if item and key:
            cast = data.setdefault(key, [])
            assert isinstance(cast, list)
            cast.append(item.group(1).strip())
            continue
        pair = re.match(r"([\w-]+):\s*(.*)", line)
        if pair:
            key = pair.group(1)
            if pair.group(2):
                data[key] = pair.group(2).strip()
    return data


def _scenes(text: str) -> list[tuple[str, dict[str, str]]]:
    parts = re.split(r"^### Scene ", text, flags=re.M)[1:]
    scenes = []
    for part in parts:
        head, _, body = part.partition("\n")
        fields = {}
        for name in (*SCENE_FIELDS, "Duration estimate"):
            m = re.search(rf"^- {re.escape(name)}: (.+)$", body, re.M)
            if m:
                fields[name] = m.group(1).strip()
        scenes.append((head.split()[0], fields))
    return scenes


def _fallback_violations(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        for name, rx in FALLBACK_BANNED.items():
            if rx.search(line) and not NEGATION.search(line):
                hits.append(f"{name}: {line.strip()}")
    return hits


def _load_rules() -> ModuleType | None:
    if not RULES_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("claims_rules", RULES_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_files_exist() -> None:
    for path in SOURCE_FILES:
        assert path.is_file(), path


def test_states_source_only_and_not_rendered() -> None:
    text = _read(STORYBOARD)
    fm = _front_matter(text)
    assert fm["status"] == "draft"
    assert fm["rendered"] == "false"
    assert fm["claims"]
    assert "source text" in text.lower()
    assert "not a rendered video" in text.lower()
    for path in SOURCE_FILES:
        assert "explainer video delivered" not in _read(path).lower()


def test_every_scene_complete_and_sources_exist() -> None:
    scenes = _scenes(_read(STORYBOARD))
    assert len(scenes) >= 5
    for sid, fields in scenes:
        for name in SCENE_FIELDS:
            assert fields.get(name), f"{sid} missing {name}"
        assert "banner" in fields["Visual"].lower(), f"{sid} must show the isolation banner"
        for src in (s.strip() for s in fields["Sources"].split(",")):
            assert (ROOT / src).is_file(), f"{sid} cites missing path {src}"


def test_scene_claims_are_declared_and_listed() -> None:
    storyboard = _read(STORYBOARD)
    declared = set(_front_matter(storyboard)["claims"])  # type: ignore[arg-type]
    claims_md = _read(CLAIMS)
    assert declared == set(_front_matter(claims_md)["claims"])  # type: ignore[arg-type]
    used = set()
    for _, fields in _scenes(storyboard):
        used |= {c.strip() for c in fields["Claims"].split(",")}
    assert used == declared
    rows = re.findall(r"^\| (C\d+) \| .+ \| (\S+) \| (.+) \|$", claims_md, re.M)
    assert {r[0] for r in rows} == declared
    for _, doc, reviewer in rows:
        assert (ROOT / doc).is_file(), doc
        reviewer = reviewer.strip()
        assert reviewer == "UNREVIEWED (pending independent review)" or (
            reviewer.startswith(("Claude reviewer agent", "Added 2026-11-03"))
            and "accepted by owner without independent review 2026-11-03" in reviewer
        )


def test_script_matches_storyboard_narration() -> None:
    narration = [f["Narration"] for _, f in _scenes(_read(STORYBOARD))]
    script = _read(SCRIPT)
    for line in narration:
        assert line in script


def test_timing_stated_as_estimates() -> None:
    text = _read(STORYBOARD)
    assert "ESTIMATES" in text
    scenes = _scenes(text)
    words = sum(len(f["Narration"].split()) for _, f in scenes)
    assert f"Narration words: {words}" in text
    total = sum(int(f["Duration estimate"].split()[0]) for _, f in scenes)
    assert f"{total} s (sum of the scene estimates" in text
    assert words / 150 * 60 <= total <= words / 150 * 60 + 2 * len(scenes)


def test_no_rendered_media_under_video() -> None:
    video = ROOT / "marketing" / "video"
    # render/out holds the gitignored local render output (PRP-27); everything else stays strict.
    local_out = video / "render" / "out"
    found = [
        p
        for p in video.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES and local_out not in p.parents
    ]
    assert not found, found


def test_no_em_dashes() -> None:
    for path in SOURCE_FILES:
        assert "—" not in _read(path), path


def test_fallback_banned_phrases() -> None:
    for path in SOURCE_FILES:
        assert _fallback_violations(_read(path)) == [], path


def test_fallback_check_catches_violations() -> None:
    assert _fallback_violations("It is FedRAMP compliant.")
    assert _fallback_violations("A unique product that saves 30 percent.")
    assert not _fallback_violations("This makes no ATO claim.")


def test_shared_claims_lint() -> None:
    rules = _load_rules()
    if rules is None:
        pytest.skip("tests/marketing/claims_rules.py not present yet (PRP-26 item 1)")
    find = getattr(rules, "find_violations", None)
    if find is None:
        pytest.skip("claims_rules.find_violations not exposed")
    for path in SOURCE_FILES:
        assert list(find(_read(path))) == [], path
