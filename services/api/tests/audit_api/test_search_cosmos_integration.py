"""The Cosmos audit search store against the vNext emulator (`docker compose up -d --wait`).

Marked ``integration``: the CI ``python`` job skips it; run it locally with the emulator up.
It proves the parameterized single-partition query runs on a real Cosmos API surface and agrees
with the in-memory twin on the same chain.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from azure.cosmos import PartitionKey
from neurosphere_api.audit.search_store import (
    AuditSearchFilter,
    CosmosAuditSearchStore,
    RepositoryAuditSearchStore,
    position_of,
)
from neurosphere_core.audit import AuditRepository, build_after, build_before
from neurosphere_core.audit.cosmos_store import PARTITION_KEY_PATH, CosmosAuditStore
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .audit_api_helpers import ctx, subject

pytestmark = pytest.mark.integration

_DOMAIN = "commercial:contoso:catalog:domain:finance"


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


async def test_emulator_search_matches_the_twin() -> None:
    chain = f"it.{uuid.uuid4().hex[:12]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = await client.create_database_if_not_exists("ns_audit_search_it")
        await db.create_container_if_not_exists(
            "audit", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        repository = AuditRepository(
            CosmosAuditStore.from_client(client, database="ns_audit_search_it", container="audit")
        )
        for i in range(6):
            draft = (
                build_before(ctx(), subject(_DOMAIN))
                if i % 2
                else build_after(
                    ctx("catalog.update"), subject(_DOMAIN), result="succeeded", verified=True
                )
            )
            await repository.append(chain, draft)
        now = datetime.now(UTC)
        flt = AuditSearchFilter(since=now - timedelta(hours=1), until=now + timedelta(hours=1))
        cosmos = CosmosAuditSearchStore.from_client(
            client, database="ns_audit_search_it", container="audit"
        )
        twin = RepositoryAuditSearchStore(repository)
        first = await cosmos.search(chain, flt, before=None, limit=4)
        assert first == await twin.search(chain, flt, before=None, limit=4)
        rest = await cosmos.search(chain, flt, before=position_of(first[-1]), limit=10)
        assert [r.sequence for r in first + rest] == [5, 4, 3, 2, 1, 0]
        only = AuditSearchFilter(
            since=flt.since, until=flt.until, operation="catalog.update", kind="after"
        )
        assert len(await cosmos.search(chain, only, before=None, limit=10)) == 3
