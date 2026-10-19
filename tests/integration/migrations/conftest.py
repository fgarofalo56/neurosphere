"""Emulator fixtures (same connection pattern as tests/integration/catalog)."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .support import Env, create_env, drop_env

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def env() -> AsyncIterator[Env]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        database = await client.create_database_if_not_exists("ns_migrations_it")
        created = await create_env(database)
        try:
            yield created
        finally:
            await drop_env(database, created)
