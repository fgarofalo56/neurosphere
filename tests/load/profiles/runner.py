"""Start a profile run. Plain Python (no locust import): locust runs as an isolated subprocess.

``uv run --isolated --no-project --with-requirements tests/load/profiles/requirements.txt
locust -f tests/load/profiles/locustfile.py --headless ...``

Enterprise and stress are never started by CI or any test; they need an explicit host and a named
environment (``definitions.resolve_run`` refuses otherwise) and are run by an operator.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .definitions import RunPlan

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = Path(__file__).resolve().parent
REQUIREMENTS = PROFILES_DIR / "requirements.txt"
LOCUSTFILE = PROFILES_DIR / "locustfile.py"
# Grace beyond the requested run time for locust startup, spawn and shutdown (seconds).
STARTUP_GRACE_SECONDS = 120


def build_command(plan: RunPlan) -> list[str]:
    """The locust argument list (never a shell string)."""
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv is required on PATH to run the isolated locust environment")
    return [
        uv,
        "run",
        "--isolated",
        "--no-project",
        "--with-requirements",
        str(REQUIREMENTS),
        "locust",
        "-f",
        str(LOCUSTFILE),
        "--headless",
        "--host",
        plan.host,
        "-u",
        str(plan.users),
        "-r",
        str(plan.users),
        "-t",
        f"{plan.duration_seconds}s",
        "--only-summary",
    ]


def build_env(
    plan: RunPlan,
    *,
    credentials_json: str,
    evidence_dir: Path,
    method: str,
    run_id: str,
    notes: dict[str, object] | None = None,
    suffix: str = "",
    seed: int = 0,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.update(
        {
            "NS_LOAD_PROFILE": plan.profile.name,
            "NS_LOAD_HOST": plan.host,
            "NS_LOAD_ENV_LABEL": plan.environment_label,
            "NS_LOAD_DURATION": str(plan.duration_seconds),
            "NS_LOAD_USERS": str(plan.users),
            "NS_LOAD_SKEW_MULTIPLE": str(plan.skew_multiple),
            "NS_LOAD_EVIDENCE_DIR": str(evidence_dir),
            "NS_LOAD_EVIDENCE_SUFFIX": suffix,
            "NS_LOAD_CREDENTIALS_JSON": credentials_json,
            "NS_LOAD_METHOD": method,
            "NS_LOAD_NOTES_JSON": json.dumps(notes or {}),
            "NS_LOAD_RUN_ID": run_id,
            "NS_LOAD_SEED": str(seed),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def run_locust(
    plan: RunPlan,
    *,
    credentials_json: str,
    evidence_dir: Path,
    method: str,
    run_id: str,
    notes: dict[str, object] | None = None,
    suffix: str = "",
    seed: int = 0,
) -> tuple[int, Path | None, str]:
    """Run locust; return (exit code, newest evidence path or None, combined output tail)."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_mtime_ns for p in evidence_dir.glob("*.json")}
    done = subprocess.run(
        build_command(plan),
        env=build_env(
            plan,
            credentials_json=credentials_json,
            evidence_dir=evidence_dir,
            method=method,
            run_id=run_id,
            notes=notes,
            suffix=suffix,
            seed=seed,
        ),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=plan.duration_seconds + STARTUP_GRACE_SECONDS,
        check=False,
    )
    fresh = [
        p
        for p in evidence_dir.glob(f"{plan.profile.name}-*.json")
        if before.get(p) != p.stat().st_mtime_ns
    ]
    newest = max(fresh, key=lambda p: p.stat().st_mtime_ns) if fresh else None
    tail = (done.stdout + "\n" + done.stderr)[-4000:]
    return done.returncode, newest, tail
