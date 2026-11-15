"""CosmosCandidateQuarantine on the compose emulator (PRP-43 item 2).

Local evidence only (the python CI job skips the ``integration`` marker). Use ``127.0.0.1``.
A "restart" is a fresh sink object over the same container: the records must still be there and
a replay must leave exactly one per candidate edge id.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from azure.cosmos import PartitionKey
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.stores.containers import container_spec
from neurosphere_workers.projections.catalog.quarantine import (
    REASON_ENTITY_COLLISION,
    CandidateQuarantineRecord,
)
from neurosphere_workers.projections.catalog.quarantine_cosmos import CosmosCandidateQuarantine

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_catalog_quarantine_it")


def _record(edge_id: str, reason: str = "out_of_scope") -> CandidateQuarantineRecord:
    return CandidateQuarantineRecord(
        id=edge_id,
        reason=reason,
        relation_type="invokes",
        source_id="commercial:qit:foundry:agent:a",
        target_id="commercial:qit:foundry:agent:b",
        cloud="commercial",
        customer_id="qit",
        domain_id="commercial:qit:foundry:domain:d",
        rule="delegation",
        quarantined_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


async def test_records_survive_a_restart_and_replay_is_idempotent(
    database: DatabaseProxy,
) -> None:
    spec = container_spec("catalog_quarantine")
    container = await database.create_container_if_not_exists(
        id=f"{spec.name}_{uuid.uuid4().hex[:8]}",
        partition_key=PartitionKey(path=list(spec.partition_key_paths), kind="MultiHash"),
    )
    try:
        first = CosmosCandidateQuarantine(container)
        await first.write(_record("commercial:qit:foundry:invokes:e1"))
        await first.write(_record("commercial:qit:foundry:invokes:e2", REASON_ENTITY_COLLISION))
        restarted = CosmosCandidateQuarantine(container)
        await restarted.write(_record("commercial:qit:foundry:invokes:e1"))  # replay
        rows = [row async for row in container.query_items("SELECT c.id, c.reason FROM c")]
        assert sorted(r["id"] for r in rows) == [
            "commercial:qit:foundry:invokes:e1",
            "commercial:qit:foundry:invokes:e2",
        ]
        assert {r["reason"] for r in rows} == {"out_of_scope", REASON_ENTITY_COLLISION}
    finally:
        await database.delete_container(container.id)
