"""Fixtures for connector integration tests: the same compose emulators as the ingestion suite.

The emulator environment and the Event Hubs restart fixtures are reused from
``tests/integration/ingestion/conftest.py`` so there is one definition of how the emulators are
prepared. Nothing here reads ``.env``.
"""

from __future__ import annotations

from integration.ingestion.conftest import _emulator_env, fresh_hub

__all__ = ["_emulator_env", "fresh_hub"]
