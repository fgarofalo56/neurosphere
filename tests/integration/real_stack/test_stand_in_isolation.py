"""PRP-38 item 6: the stand-in API launcher is test-only and unreachable from product code.

Plain unit test (no emulators): it scans the repo for any reference to the launcher outside tests,
the Playwright harness and the CI workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[3]
NAME: Final = "serve_stand_in_api"
ALLOWED: Final = (
    "tests/",
    "frontend/tests/real-stack/",
    "frontend/playwright.real-stack.config.ts",
    ".github/workflows/real-stack.yml",
    "PRPs/",
    "docs/",
)
SCANNED: Final = ("services", "packages", "connectors", "scripts", "infra", "docker-compose.yml")


def test_launcher_is_referenced_only_by_the_test_harness() -> None:
    offenders: list[str] = []
    for entry in SCANNED:
        base = ROOT / entry
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(ALLOWED) or "node_modules" in rel or "/.venv/" in rel:
                continue
            if path.suffix not in {".py", ".yml", ".yaml", ".toml", ".sh", ".json", ".mk", ""}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if NAME in text:
                offenders.append(rel)
    assert not offenders, f"product code references the test-only stand-in API: {offenders}"
