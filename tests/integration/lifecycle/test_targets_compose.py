"""Lifecycle adapters against the compose Cosmos emulator (`docker compose up -d --wait`).

A thin Cosmos-backed DocumentBackend proves the BackendTarget adapter deletes, pseudonymizes and
reads back against a real store. Emulator limits apply (no auth enforcement, no RU accounting).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.lifecycle.adapters import CatalogTarget

pytestmark = pytest.mark.integration

PK = "/pk"


class _CosmosDocs:
    def __init__(self, container: ContainerProxy) -> None:
        self._c = container

    async def read(self, record_id: str) -> Mapping[str, Any] | None:
        try:
            return await self._c.read_item(item=record_id, partition_key="p")
        except CosmosResourceNotFoundError:
            return None

    async def remove(self, record_id: str) -> None:
        try:
            await self._c.delete_item(item=record_id, partition_key="p")
        except CosmosResourceNotFoundError:
            return

    async def page(self, data_class: str, limit: int, after: str | None) -> list[Mapping[str, Any]]:
        query = "SELECT * FROM c WHERE c.data_class = @d ORDER BY c.id"
        items = self._c.query_items(query, parameters=[{"name": "@d", "value": data_class}])
        out = [d async for d in items if after is None or d["id"] > after]
        return out[:limit]

    async def redact_subject(self, record_id: str) -> None:
        doc = dict(await self._c.read_item(item=record_id, partition_key="p"))
        doc["subject_id"] = None
        doc["pseudonymized"] = True
        await self._c.replace_item(item=record_id, body=doc)

    async def project(self, record_id: str) -> Mapping[str, Any]:
        doc = await self._c.read_item(item=record_id, partition_key="p")
        return {"id": doc["id"], "data_class": doc["data_class"]}


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_lifecycle_it")


async def test_delete_and_pseudonymize_read_back_against_emulator(
    database: DatabaseProxy,
) -> None:
    container = await database.create_container_if_not_exists(
        f"lc_{uuid.uuid4().hex[:8]}", partition_key=PartitionKey(path=PK)
    )
    try:
        created = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        for rid in ("a", "b"):
            await container.create_item(
                {
                    "id": rid,
                    "pk": "p",
                    "data_class": "telemetry",
                    "created_at": created,
                    "subject_id": f"subj-{uuid.uuid4().hex[:6]}",
                }
            )
        target = CatalogTarget("records", _CosmosDocs(container))
        before = await target.get("a")
        assert before is not None
        await target.delete("a")
        assert await target.get("a") is None  # read-back
        await target.pseudonymize("b")
        after = await target.get("b")
        assert after is not None
        assert after.pseudonymized
        assert after.subject_id is None
        listed = await target.list_records(data_class="telemetry", limit=10, after=None)
        assert [r.record_id for r in listed] == ["b"]
    finally:
        await database.delete_container(container.id)
