# pyright: reportMissingImports=false
"""Sandbox repository against the Cosmos emulator: reads sandbox data, refuses real containers."""

from __future__ import annotations

from pathlib import Path

import pytest
from azure.cosmos import PartitionKey
from neurosphere_api.sandbox.models import SandboxKind
from neurosphere_api.sandbox.repository import (
    ALLOWED_DATABASE,
    ENTITIES_CONTAINER,
    RELATIONS_CONTAINER,
    CosmosSandboxStore,
    SandboxRepository,
)
from neurosphere_core.errors import InvalidSchemaError
from sbx_seam import CosmosSeam

from .conftest import cli_json, run_cli

pytestmark = pytest.mark.integration


def _async_client():
    from azure.cosmos.aio import CosmosClient
    from sbx_guard import cosmos_settings

    endpoint, key = cosmos_settings(None)
    return CosmosClient(endpoint, credential=key)


async def test_repository_reads_seeded_sandbox_and_refuses_real_containers(
    stack: None, data_dir: Path
) -> None:
    assert run_cli("reset").returncode == 0
    seeded = cli_json("seed", "--data-dir", str(data_dir), "--no-events")
    assert seeded["documents"]["created"] > 0

    seam = CosmosSeam()
    expected_entities = seam.count(ALLOWED_DATABASE, ENTITIES_CONTAINER)
    expected_relations = seam.count(ALLOWED_DATABASE, RELATIONS_CONTAINER)

    # A non-sandbox container exists on the same account; it must stay unreachable.
    real = seam._client.create_database_if_not_exists(id="ns-it-real")
    real.create_container_if_not_exists(id="entities", partition_key=PartitionKey(path="/id"))

    client = _async_client()
    try:
        repo = SandboxRepository(CosmosSandboxStore(client))
        counts = await repo.counts_by_kind()
        assert sum(counts.values()) == expected_entities
        assert await repo.count_container(RELATIONS_CONTAINER) == expected_relations
        page = await repo.list_entities(SandboxKind.AGENT, 5, 0)
        assert page
        assert all(doc["entity_type"] == "agent" for doc in page)

        for name in ("entities", "catalog", "sandbox-catalog"):
            with pytest.raises(InvalidSchemaError):
                await repo.count_container(name)
            with pytest.raises(InvalidSchemaError):
                await CosmosSandboxStore(client).count(ALLOWED_DATABASE, name, None)
        with pytest.raises(InvalidSchemaError):
            await CosmosSandboxStore(client).count("ns-it-real", "entities", None)
        with pytest.raises(InvalidSchemaError):
            SandboxRepository(CosmosSandboxStore(client), database="ns-it-real")
    finally:
        await client.close()
        seam._client.delete_database("ns-it-real")
        run_cli("reset")
