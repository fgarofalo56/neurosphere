"""Every test starts with no composition, copilot or MCP settings in the environment.

``services/api/tests`` is on ``sys.path`` through rootdir insertion (this package's parent), so
the PRP-06 harness (``authz.authz_helpers``) and item 1's ``runtime_api.runtime_helpers`` import.
"""

from __future__ import annotations

import os

import pytest

_PREFIXES = (
    "NS_AUTH_",
    "NS_STORE_",
    "NS_CORS_",
    "NS_COSMOS_",
    "NS_REVOCATION_",
    "NS_COPILOT_",
    "NS_MCP_",
)
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED")


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
