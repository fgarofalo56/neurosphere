"""Gateway builder tests: clean composition env and the sibling harnesses on ``sys.path``.

This directory has no ``__init__.py`` (unique name, imported by module name like gateway_api).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
for _path in (_TESTS, _TESTS / "gateway_api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_PREFIXES = ("NS_AUTH_", "NS_STORE_", "NS_CORS_", "NS_COSMOS_", "NS_REVOCATION_", "NS_GATEWAY_")
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED", "NS_MCP_RESOURCE_SERVER_URL")


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
