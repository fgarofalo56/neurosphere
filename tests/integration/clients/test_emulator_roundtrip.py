"""Round trip through the compose emulators via the factories (`docker compose up -d --wait`).

Emulator limits (PRP-05 C4): Cosmos vNext has no auth enforcement or RU accounting; the Event
Hubs emulator is SAS-only. Passing here says nothing about RBAC, RU, indexing or Entra.
"""

from __future__ import annotations

import asyncio
import base64
import uuid

import pytest
from azure.cosmos import PartitionKey
from neurosphere_core.clients import (
    ClientLifetime,
    create_cosmos_client,
    create_eventhub_consumer,
    create_eventhub_producer,
)
from neurosphere_core.cloud import Settings

pytestmark = pytest.mark.integration

# Documented placeholder for the Event Hubs emulator (SAS_KEY_VALUE is the emulator's literal
# placeholder per Microsoft docs; the emulator does not validate it). Cosmos vNext ignores the key.
_EH_CONN = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    monkeypatch.setenv("NS_EVENTHUBS_CONNECTION_STRING", _EH_CONN)


async def test_cosmos_document_roundtrip() -> None:
    settings = Settings(env="local")
    async with ClientLifetime() as lt:
        client = create_cosmos_client(settings, lifetime=lt)
        db = await client.create_database_if_not_exists("ns_roundtrip")
        container = await db.create_container_if_not_exists(
            "items", partition_key=PartitionKey(path="/pk")
        )
        doc_id = uuid.uuid4().hex
        await container.upsert_item({"id": doc_id, "pk": "t1", "value": 42})
        got = await container.read_item(doc_id, partition_key="t1")
        assert got["value"] == 42


async def test_eventhub_send_receive() -> None:
    settings = Settings(env="local")
    marker = uuid.uuid4().hex
    received: list[str] = []
    got = asyncio.Event()

    async with ClientLifetime() as lt:
        consumer = create_eventhub_consumer(
            settings, lifetime=lt, eventhub_name="telemetry", consumer_group="$default"
        )
        producer = create_eventhub_producer(settings, lifetime=lt, eventhub_name="telemetry")

        async def on_event(ctx: object, event: object) -> None:
            if event is None:
                return
            body = event.body_as_str()  # type: ignore[attr-defined]
            if body == marker:
                received.append(body)
                got.set()

        recv = asyncio.create_task(
            consumer.receive(on_event=on_event, starting_position="@latest")  # type: ignore[arg-type]
        )
        try:
            await asyncio.sleep(3)  # let partition receivers attach before sending
            from azure.eventhub import EventData

            batch = await producer.create_batch()
            batch.add(EventData(marker))
            await producer.send_batch(batch)
            await asyncio.wait_for(got.wait(), timeout=30)
        finally:
            recv.cancel()
            await asyncio.gather(recv, return_exceptions=True)
        assert received == [marker]
