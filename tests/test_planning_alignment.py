"""The planning validator is also a pytest gate so the kit's test gate has real work."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_planning_artifacts_are_aligned() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "validate_planning.py"))
    assert namespace["main"]() == 0, "see printed failures above"
