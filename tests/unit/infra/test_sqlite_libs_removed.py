"""PRP-52 (#171): sqlite-libs is removed from the runtime images instead of ignored by Grype.

Static checks only; the image builds and the in-image import check are recorded in the PR (they
need Docker). The lazy import is checked for real in a subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILES = [
    ROOT / "services" / "api" / "Dockerfile",
    ROOT / "services" / "workers" / "Dockerfile",
    ROOT / "services" / "docs-assistant" / "Dockerfile",
]


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.parent.name)
def test_final_stage_removes_sqlite_libs_and_repins_the_rest(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    final_stage = text.rsplit("\nFROM ", 1)[-1]
    # `apk del sqlite-libs` alone is a no-op: .python-rundeps depends on libsqlite3.
    assert "apk del --no-cache .python-rundeps sqlite-libs" in final_stage
    assert "apk add --no-cache --virtual .ns-rundeps" in final_stage
    assert "grep -v 'libsqlite3'" in final_stage


def test_grype_config_has_no_sqlite_rule() -> None:
    text = (ROOT / ".grype.yaml").read_text(encoding="utf-8")
    rules = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any("sqlite" in line for line in rules)


def test_importing_the_analytics_package_does_not_load_sqlite3() -> None:
    code = (
        "import sys, neurosphere_core.analytics; "
        "sys.exit(1 if ('sqlite3' in sys.modules or '_sqlite3' in sys.modules) else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=120
    )
    assert proc.returncode == 0, proc.stderr or "sqlite3 was imported by neurosphere_core.analytics"
