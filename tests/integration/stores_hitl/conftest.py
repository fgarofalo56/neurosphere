"""Emulator fixtures: a throwaway database per test, deleted afterwards.

Run (emulators already up; never start compose from a test):
``MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/stores_hitl``.
The emulator ignores the key, so a dummy one is built at runtime (no credential-shaped literal).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        name = f"ns_stores_hitl_{uuid.uuid4().hex[:10]}"
        created = await client.create_database_if_not_exists(name)
        try:
            yield created
        finally:
            await client.delete_database(name)
