"""``ensure_local_containers`` against the compose Cosmos emulator (``integration``).

Run: ``docker compose up -d --wait`` then ``pytest -m integration
packages/core/tests/stores_registry``. Uses its own database (deleted afterwards); the CI-run
sibling with a fake client is ``test_registry.py``.
"""

from __future__ import annotations

import base64
import uuid

import pytest
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.stores import CONTAINERS, ensure_local_containers

pytestmark = pytest.mark.integration


async def test_every_container_is_created_with_its_declared_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    settings = Settings(env="local")
    name = f"ns_registry_it_{uuid.uuid4().hex[:8]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(settings, lifetime=lifetime)
        try:
            ensured = await ensure_local_containers(client, settings, database=name)
            again = await ensure_local_containers(client, settings, database=name)  # idempotent
            assert ensured == again == tuple(spec.name for spec in CONTAINERS)
            database = client.get_database_client(name)
            for spec in CONTAINERS:
                properties = await database.get_container_client(spec.name).read()
                key = properties["partitionKey"]
                assert key["paths"] == list(spec.partition_key_paths), spec.name
                assert key.get("kind", "Hash") == spec.kind, spec.name
                if spec.default_ttl is not None:
                    assert properties.get("defaultTtl") == spec.default_ttl, spec.name
        finally:
            await client.delete_database(name)
