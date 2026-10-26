"""Every test starts from an environment with no composition settings (no emulator, no tenant).

The shared PRP-06 harness (``services/api/tests/authz``) is importable because this package's
parent directory is on ``sys.path`` (rootdir insertion; ``authz`` is a package).
"""

from __future__ import annotations

import os

import pytest

_PREFIXES = ("NS_AUTH_", "NS_STORE_", "NS_CORS_", "NS_COSMOS_", "NS_REVOCATION_", "NS_COPILOT_")
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED", "NS_MCP_RESOURCE_SERVER_URL")


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
