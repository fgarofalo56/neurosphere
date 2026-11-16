"""System admin API tests (PRP-45): clean composition env and sibling harnesses on ``sys.path``.

This directory has no ``__init__.py`` (unique name, imported by module name like gateway_api).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from neurosphere_core.admin.runtime import PROCESS_CACHE

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _path in (_TESTS, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_PREFIXES = (
    "NS_AUTH_",
    "NS_STORE_",
    "NS_CORS_",
    "NS_COSMOS_",
    "NS_REVOCATION_",
    "NS_GATEWAY_",
    "NS_COPILOT_",
    "NS_SEARCH_",
    "NS_SCAN_",
    "NS_MCP_",
    "NS_FOUNDRY_",
    "NS_APIM_",
    "NS_WORKER_EVAL_",
)
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE")


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
    PROCESS_CACHE.clear()
