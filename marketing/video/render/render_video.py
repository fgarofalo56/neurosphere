"""PRP-27 render entry point: guard, parse storyboard, emit captions, run a backend.

Entry point: ``python marketing/video/render/render_video.py`` (function ``main``).

No paid or network call is made here. The only backend that works without operator
involvement is ``StubBackend``. The real backend is a placeholder: the tool is chosen at
execution time together with the operator.

``LocalBackend`` runs fixed local tools (node, pnpm, powershell, ffmpeg, ffprobe) found on
PATH with no untrusted input, hence the file-level subprocess waivers below.
"""

# ruff: noqa: S603, S607

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[3]
VIDEO_DIR = ROOT / "marketing" / "video"
APPROVAL_PATH = VIDEO_DIR / "APPROVAL.md"
STORYBOARD_PATH = VIDEO_DIR / "storyboard" / "storyboard.md"
SCRIPT_PATH = VIDEO_DIR / "storyboard" / "script.md"
SPEND_LOG_PATH = VIDEO_DIR / "render" / "spend-log.md"
RULES_PATH = ROOT / "tests" / "marketing" / "claims_rules.py"

REQUIRED_FIELDS = (
    "Date",
    "Budget amount",
    "Currency",
    "Approver",
    "Approved tool",
    "Tool version",
    "Tool terms URL",
    "Terms observed date",
    "Approved scope",
    "Voice and likeness licensing terms",
    "Storage decision (commit or external)",
    "Storage checksum",
)
PAUSE_SECONDS = 1.0


class GuardError(Exception):
    """The approval record is missing, malformed or incomplete, or the run is not allowed."""


class BudgetExceededError(Exception):
    """A charge would pass the approved budget cap."""


@dataclass(frozen=True)
class Approval:
    fields: dict[str, str]
    budget: Decimal
    currency: str


@dataclass(frozen=True)
class Scene:
    scene_id: str
    title: str
    narration: str
    duration_s: float


def parse_approval(path: Path) -> Approval:
    """Parse the approval table; raise GuardError on any missing, empty or TODO field."""
    if not path.is_file():
        raise GuardError(f"approval file missing: {path}")
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= set("-: "):
            continue
        found[cells[0]] = cells[1]
    if not found:
        raise GuardError(f"approval file malformed (no Field | Value table): {path}")
    bad = [
        name
        for name in REQUIRED_FIELDS
        if name not in found or not found[name] or "TODO" in found[name].upper()
    ]
    if bad:
        raise GuardError("approval incomplete (missing, empty or TODO): " + ", ".join(bad))
    try:
        budget = Decimal(found["Budget amount"].replace(",", ""))
    except InvalidOperation as exc:
        raise GuardError(f"Budget amount is not a number: {found['Budget amount']!r}") from exc
    if not budget.is_finite() or budget <= 0:
        raise GuardError("Budget amount must be a finite number greater than zero")
    return Approval(fields=found, budget=budget, currency=found["Currency"])


def check_live_gate(backend_name: str, env: Mapping[str, str] | None = None) -> None:
    """Refuse a non-stub backend unless NS_LIVE_APPROVED=1."""
    environ = os.environ if env is None else env
    if backend_name != "stub" and environ.get("NS_LIVE_APPROVED") != "1":
        raise GuardError("non-stub backend requires NS_LIVE_APPROVED=1 (operator approval)")


def parse_scenes(storyboard: Path = STORYBOARD_PATH) -> list[Scene]:
    """Read scenes from storyboard.md ('### Scene Sxx Title' blocks)."""
    text = storyboard.read_text(encoding="utf-8")
    scenes: list[Scene] = []
    for block in re.split(r"^### Scene ", text, flags=re.MULTILINE)[1:]:
        head, _, body = block.partition("\n")
        match = re.match(r"(S\d+)\s+(.*)", head.strip())
        narr = re.search(r"^- Narration: (.+)$", body, flags=re.MULTILINE)
        dur = re.search(r"^- Duration estimate: ([\d.]+) s", body, flags=re.MULTILINE)
        if not (match and narr and dur):
            raise GuardError(f"malformed scene block: {head!r}")
        scenes.append(Scene(match[1], match[2], narr[1].strip(), float(dur[1])))
    if not scenes:
        raise GuardError(f"no scenes found in {storyboard}")
    return scenes


def parse_script(script: Path = SCRIPT_PATH) -> dict[str, str]:
    """Read narration per scene id from script.md ('## Sxx Title' sections)."""
    text = script.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head, _, body = block.partition("\n")
        match = re.match(r"(S\d+)\b", head.strip())
        if match:
            out[match[1]] = " ".join(body.split())
    return out


def _timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def build_vtt(scenes: list[Scene]) -> str:
    """WebVTT with one cue per scene; cue text is the narration, timing is the estimate."""
    lines = ["WEBVTT", ""]
    start = 0.0
    for scene in scenes:
        end = start + scene.duration_s
        lines += [scene.scene_id, f"{_timestamp(start)} --> {_timestamp(end - PAUSE_SECONDS)}"]
        lines += [scene.narration, ""]
        start = end
    return "\n".join(lines)


def transcript(scenes: list[Scene]) -> str:
    return "\n\n".join(s.narration for s in scenes) + "\n"


def lint_transcript(text: str) -> list[str]:
    """Run the shared claims lint (PRP-26) on the transcript; return violation strings."""
    spec = importlib.util.spec_from_file_location("claims_rules", RULES_PATH)
    if spec is None or spec.loader is None:
        raise GuardError(f"cannot load claims rules: {RULES_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["claims_rules"] = module  # dataclasses need this before exec
    spec.loader.exec_module(module)
    return [str(v) for v in module.find_violations(text)]


class Backend(Protocol):
    name: str

    def render_scene(self, scene: Scene) -> Decimal:
        """Render one scene and return the cost incurred."""
        ...


@dataclass
class StubBackend:
    """Test backend: no media, no network, fixed per-scene cost."""

    name: str = "stub"
    cost_per_scene: Decimal = Decimal(0)
    rendered: list[str] = field(default_factory=list)

    def render_scene(self, scene: Scene) -> Decimal:
        self.rendered.append(scene.scene_id)
        return self.cost_per_scene


class RealBackend:
    """Placeholder. The real tool is chosen at execution time with the operator."""

    name = "real"

    def render_scene(self, scene: Scene) -> Decimal:
        raise NotImplementedError(
            "No real backend is implemented. The video tool is chosen at execution time "
            "together with the operator, after APPROVAL.md names it; implement it then."
        )


Runner = Callable[..., "subprocess.CompletedProcess[str]"]
SCENE_FPS = 25
VOICE = "Microsoft Zira Desktop"


def _wait_http(url: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):  # noqa: S310 (loopback only)
                return
        except OSError:
            time.sleep(1.0)
    raise GuardError(f"local server did not come up: {url}")


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], check=False, capture_output=True
        )


class LocalBackend:
    """Zero-cost local pipeline: Playwright capture, System.Speech voice, ffmpeg assembly.

    No paid service and no network media API. Only loopback servers are contacted.
    """

    name = "local"

    def __init__(
        self,
        out_dir: Path,
        app_port: int = 5217,
        api_port: int = 5218,
        runner: Runner | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.app_port = app_port
        self.api_port = api_port
        self.run_cmd: Runner = runner or subprocess.run
        self.frames = out_dir / "frames"
        self.audio = out_dir / "audio"
        self.clips = out_dir / "clips"
        self.measured: dict[str, float] = {}
        self.shots: dict[str, list[str]] = {}

    # -- helpers -------------------------------------------------------------------------
    def _run(self, cmd: list[str], cwd: Path | None = None) -> str:
        result = self.run_cmd(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise GuardError(f"command failed ({cmd[0]}): {(result.stderr or '')[-400:]}")
        return result.stdout or ""

    def probe_duration(self, media: Path) -> float:
        out = self._run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(media),
            ]
        )  # fmt: skip
        return float(out.strip())

    # -- capture -------------------------------------------------------------------------
    def prepare(self) -> None:
        """Capture every scene's frames once, against loopback servers started here."""
        for folder in (self.frames, self.audio, self.clips):
            folder.mkdir(parents=True, exist_ok=True)
        frontend = ROOT / "frontend"
        app_origin = f"http://127.0.0.1:{self.app_port}"
        env = {
            **os.environ,
            "NS_MOCK_API_PORT": str(self.api_port),
            "NS_E2E_APP_ORIGIN": app_origin,
        }
        pnpm = shutil.which("pnpm") or "pnpm"
        quiet = subprocess.DEVNULL
        procs = [
            subprocess.Popen(
                ["node", "tests/mock-api/server.ts"],
                cwd=frontend,
                env=env,
                stdout=quiet,
                stderr=quiet,
            ),
            subprocess.Popen(
                [pnpm, "exec", "vite", "--mode", "e2e", "--host", "127.0.0.1",
                 "--port", str(self.app_port), "--strictPort"],
                cwd=frontend,
                env=env,
                stdout=quiet,
                stderr=quiet,
            ),
        ]  # fmt: skip
        try:
            _wait_http(f"http://127.0.0.1:{self.api_port}/api/v1/health")
            _wait_http(app_origin)
            self._run(
                ["node", str(VIDEO_DIR / "render" / "capture.mjs"), str(frontend),
                 str(self.frames), str(self.app_port), str(self.api_port)]
            )  # fmt: skip
        finally:
            for proc in procs:
                _kill_tree(proc)
        self.shots = json.loads((self.frames / "shots-result.json").read_text(encoding="utf-8"))

    # -- per scene -----------------------------------------------------------------------
    def render_scene(self, scene: Scene) -> Decimal:
        if not self.shots:
            self.prepare()
        text_file = self.audio / f"{scene.scene_id}.txt"
        wav = self.audio / f"{scene.scene_id}.wav"
        text_file.write_text(scene.narration, encoding="utf-8")
        self._run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(VIDEO_DIR / "render" / "speak.ps1"), "-TextFile", str(text_file),
             "-OutWav", str(wav), "-Voice", VOICE]
        )  # fmt: skip
        spoken = self.probe_duration(wav)
        self.measured[scene.scene_id] = spoken
        total = spoken + PAUSE_SECONDS
        images = self.shots[scene.scene_id]
        each = total / len(images)
        listing = self.clips / f"{scene.scene_id}.txt"
        rows = [f"file '{(self.frames / n).as_posix()}'\nduration {each:.3f}" for n in images]
        rows.append(f"file '{(self.frames / images[-1]).as_posix()}'")
        listing.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self._run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-i", str(wav),
             "-vf", f"scale=1280:720,fps={SCENE_FPS},format=yuv420p",
             "-af", f"apad=whole_dur={total:.3f}", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-ac", "2",
             str(self.clips / f"{scene.scene_id}.mp4")]
        )  # fmt: skip
        return Decimal("0.00")

    def measured_scenes(self, scenes: list[Scene]) -> list[Scene]:
        """Scenes whose duration is the measured narration length plus the pause."""
        return [replace(s, duration_s=self.measured[s.scene_id] + PAUSE_SECONDS) for s in scenes]

    # -- assembly ------------------------------------------------------------------------
    def finalize(self, scenes: list[Scene], captions: Path) -> str:
        """Join the scene clips, mux the VTT as a soft subtitle, and return the sha256 label."""
        listing = self.clips / "all.txt"
        listing.write_text(
            "".join(f"file '{(self.clips / f'{s.scene_id}.mp4').as_posix()}'\n" for s in scenes),
            encoding="utf-8",
        )
        joined = self.clips / "joined.mp4"
        self._run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", str(joined)]
        )  # fmt: skip
        final = self.out_dir / "neurosphere-explainer.mp4"
        self._run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-i", str(captions),
             "-map", "0:v", "-map", "0:a", "-map", "1:0", "-c", "copy", "-c:s", "mov_text",
             "-metadata:s:s:0", "language=eng", str(final)]
        )  # fmt: skip
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        return f"neurosphere-explainer.mp4 sha256 {digest}"


class SpendTracker:
    """Appends spend rows to the log and stops hard at the approved budget cap."""

    def __init__(self, log_path: Path, cap: Decimal, currency: str) -> None:
        self.log_path = log_path
        self.cap = cap
        self.currency = currency
        self.total = Decimal(0)

    def charge(self, label: str, amount: Decimal) -> None:
        if self.total + amount > self.cap:
            self._append(label, amount, "REFUSED (cap)")
            raise BudgetExceededError(
                f"charge {amount} {self.currency} would pass cap {self.cap} {self.currency}"
            )
        self.total += amount
        self._append(label, amount, "ok")

    def _append(self, label: str, amount: Decimal, status: str) -> None:
        new = not self.log_path.exists()
        with self.log_path.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("| Time (UTC) | Item | Amount | Currency | Running total | Status |\n")
                fh.write("|---|---|---|---|---|---|\n")
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(
                f"| {stamp} | {label} | {amount} | {self.currency} | {self.total} | {status} |\n"
            )


def run(
    backend: Backend,
    approval_path: Path = APPROVAL_PATH,
    out_dir: Path | None = None,
    spend_log: Path = SPEND_LOG_PATH,
    storyboard: Path = STORYBOARD_PATH,
    env: Mapping[str, str] | None = None,
) -> int:
    """Guard, then lint, caption and render. Returns a process exit code."""
    try:
        approval = parse_approval(approval_path)
        check_live_gate(backend.name, env)
        scenes = parse_scenes(storyboard)
        problems = lint_transcript(transcript(scenes))
        if problems:
            raise GuardError("claims lint failed on transcript: " + "; ".join(problems))
        target = out_dir or VIDEO_DIR / "render" / "out"
        target.mkdir(parents=True, exist_ok=True)
        (target / "captions.vtt").write_text(build_vtt(scenes), encoding="utf-8")
        tracker = SpendTracker(spend_log, approval.budget, approval.currency)
        for scene in scenes:
            cost = backend.render_scene(scene)
            tracker.charge(scene.scene_id, cost)
        if isinstance(backend, LocalBackend):
            # Cue timing comes from the measured narration audio, not the estimates.
            captions = target / "captions.vtt"
            captions.write_text(build_vtt(backend.measured_scenes(scenes)), encoding="utf-8")
            tracker.charge(backend.finalize(scenes, captions), Decimal("0.00"))
    except (GuardError, BudgetExceededError, NotImplementedError) as exc:
        print(f"render refused: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRP-27 explainer video render (guarded)")
    parser.add_argument("--backend", choices=["stub", "real", "local"], default="stub")
    parser.add_argument("--app-port", type=int, default=5217)
    parser.add_argument("--api-port", type=int, default=5218)
    args = parser.parse_args(argv)
    if args.backend == "local":
        out = VIDEO_DIR / "render" / "out"
        return run(LocalBackend(out, args.app_port, args.api_port))
    if args.backend == "stub":
        # The stub never writes into the real out dir or the real spend log.
        scratch = Path(tempfile.mkdtemp(prefix="ns-render-stub-"))
        return run(StubBackend(), out_dir=scratch, spend_log=scratch / "spend-log.md")
    return run(RealBackend())


if __name__ == "__main__":
    sys.exit(main())
