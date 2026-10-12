"""Audit store against the Cosmos vNext emulator (`docker compose up -d --wait`).

Emulator delta (PRP-06 C10, G12): the emulator enforces no auth and cannot prove service-side
immutability. This test proves only that the repository's own code paths never mutate a
written record and that the chain verifies against a real Cosmos API surface.
"""

from __future__ import annotations

import asyncio
import base64
import uuid

import pytest
from azure.cosmos import PartitionKey
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.cosmos_store import PARTITION_KEY_PATH, CosmosAuditStore
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .audit_helpers import mixed_drafts

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


async def test_emulator_append_verify_and_records_never_rewritten() -> None:
    chain = f"it.{uuid.uuid4().hex[:12]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = await client.create_database_if_not_exists("ns_audit_it")
        await db.create_container_if_not_exists(
            "audit", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        store = CosmosAuditStore.from_client(client, database="ns_audit_it", container="audit")
        writers = [AuditRepository(store) for _ in range(4)]
        await asyncio.gather(
            *(w.append(chain, d) for w, d in zip(writers * 3, mixed_drafts(12), strict=True))
        )
        first = await writers[0].read_range(chain, limit=500)
        assert [r.sequence for r in first] == list(range(12))
        for draft in mixed_drafts(4):
            await writers[0].append(chain, draft)
        again = await writers[0].read_range(chain, limit=500)
        assert [r.model_dump() for r in again[:12]] == [r.model_dump() for r in first]
        result = await writers[0].verify(chain)
        assert result.ok and result.records_checked == 16
