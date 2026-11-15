"""Admission API tests: the shared PRP-06 authz harness on ``sys.path``.

This directory has no ``__init__.py`` (unique name, imported by module name).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))


@pytest.fixture(autouse=True)
def _clean_admission_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NS_ADMISSION_ENABLED", "NS_ADMISSION_POLICY_FILE"):
        monkeypatch.delenv(name, raising=False)
