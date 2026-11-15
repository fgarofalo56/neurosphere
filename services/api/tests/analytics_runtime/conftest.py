"""Analytics builder tests: clean ``NS_ANALYTICS_*`` env and the sibling harnesses on ``sys.path``.

This directory has no ``__init__.py`` (unique name, imported by module name).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))


@pytest.fixture(autouse=True)
def _clean_analytics_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith("NS_ANALYTICS_") or name == "NS_CLOUD":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
