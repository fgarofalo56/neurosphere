"""PRP-23 round 2 backends and job store against the compose Cosmos emulator.

NOT RUN in the PRP-23 round 2 session (PRP-38 held the compose stack). Run it when the stack is
up: ``MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/lifecycle``.
Uses 127.0.0.1 (not localhost) and a throwaway container per test.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azure.cosmos import PartitionKey
from azure.cosmos.aio import DatabaseProxy
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger.lifecycle_delete import LedgerLifecycleBackend
from neurosphere_core.lifecycle import ActionKind, JobStatus, LifecycleOutcome, LifecycleRequest
from neurosphere_core.lifecycle import TargetRef as Ref
from neurosphere_core.lifecycle.cosmos import CosmosRequestQueue
from neurosphere_core.lifecycle.jobs import CosmosJobStore, JobState, LifecycleJob
from neurosphere_core.scope import IdentityScope

pytestmark = pytest.mark.integration

CUSTOMER = "contoso"


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_lifecycle_it")


def _ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + "0" * 64,
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-23", operation="lifecycle.run", channel="worker"
    )


async def test_ledger_backend_deletes_and_reads_back_absent(database: DatabaseProxy) -> None:
    container = await database.create_container_if_not_exists(
        f"ledger_{uuid.uuid4().hex[:8]}", partition_key=PartitionKey(path="/customer_id")
    )
    try:
        await container.create_item(
            {
                "id": "e1",
                "doc_type": "entry",
                "customer_id": CUSTOMER,
                "cloud": "commercial",
                "occurred_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            }
        )
        backend = LedgerLifecycleBackend(container, customer_id=CUSTOMER)
        assert await backend.read("e1") is not None
        await backend.remove("e1")
        assert await backend.read("e1") is None
        await backend.remove("e1")  # missing is a no-op
    finally:
        await database.delete_container(container.id)


async def test_job_store_shares_the_queue_container_without_cross_talk(
    database: DatabaseProxy,
) -> None:
    container = await database.create_container_if_not_exists(
        f"requests_{uuid.uuid4().hex[:8]}", partition_key=PartitionKey(path="/customer_id")
    )
    try:
        jobs = CosmosJobStore(container, customer_id=CUSTOMER)
        queue = CosmosRequestQueue(container, customer_id=CUSTOMER)
        job = LifecycleJob(
            request=LifecycleRequest(
                action=ActionKind.DELETE,
                target=Ref(target_kind="catalog", container="catalog", record_id="r1"),
            ),
            ctx=_ctx(),
            requested_by="p-7f3a9c21",
            submitted_at=datetime.now(UTC),
        )
        stored, created = await jobs.submit(job)
        assert created is True
        assert [j.job_id for j in await jobs.claim(None, 10)] == [stored.job_id]
        assert await queue.pending() == []  # job documents never appear as queued requests
        outcome = LifecycleOutcome(
            request_id=stored.job_id,
            action=ActionKind.DELETE,
            status=JobStatus.COMPLETED,
            reason="dry_run:would_delete",
            dry_run=True,
        )
        assert await jobs.record_outcome(stored.job_id, outcome) is True
        done = await jobs.get(stored.job_id)
        assert done is not None and done.state is JobState.DONE
        assert await jobs.claim(None, 10) == []
    finally:
        await database.delete_container(container.id)
