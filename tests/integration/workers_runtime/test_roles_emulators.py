"""Worker roles in ONE process against the compose emulators.

A pushed sandbox trace (plus a few cost records) must reach the ledger, the aggregates and the
catalog through the real role wiring. Two modes, one test body:

* ``hub``: Event Hubs -> the ``ingestion`` role -> archive/ledger/outbox -> the ``aggregates``
  and ``projections`` roles drain the outbox. Skipped (reported OPEN) when the Event Hubs
  emulator does not answer a short probe; this suite never restarts it.
* ``seeded``: the SAME ingestion pipeline (``process_batch`` over ``build_pipeline_deps``) lands
  the messages in-process, then the ``aggregates`` and ``projections`` roles drain the outbox.
  Proves the roles' stores, archive reader and scope wiring without the hub.

One bounded wait, polled every few seconds; nothing here starts or stops docker compose.
Run: ``MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/workers_runtime``.
Emulator limits (G12): no auth and no RU accounting; this proves the wiring and the SQL shapes,
not RBAC, throttling or production sizing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from azure.eventhub import EventData, EventHubProducerClient
from azure.storage.blob.aio import ContainerClient
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope import (
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
)
from neurosphere_core.auth.scope.policy import principal_document_id
from neurosphere_core.clients import ClientLifetime, create_cosmos_client, create_eventhub_producer
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.payload import HubMessage, HubMessageKind
from neurosphere_core.stores import ensure_local_containers
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.ingestion.wiring import build_pipeline_deps
from neurosphere_workers.runtime.factories import RuntimeConfig, role_factories
from neurosphere_workers.runtime.identity import resolve_pseudonym_key
from neurosphere_workers.runtime.supervisor import RoleSupervisor

from .support import (
    EVENTHUBS_CONNECTION,
    HUB,
    WORKER_OBJECT_ID,
    WORKER_TENANT_ID,
    Doc,
    sandbox_trace_bundle,
)

pytestmark = pytest.mark.integration

CUSTOMER = "synthco"
WAIT_SECONDS = 240
POLL_SECONDS = 3
HUB_PROBE_SECONDS = 20


def _message(doc: Doc, kind: str) -> HubMessage:
    event_id = doc["event_id"] if kind == "telemetry" else doc["cost_id"]
    return HubMessage(
        kind=HubMessageKind(kind),
        event_id=event_id,
        cloud=doc["cloud"],
        customer_id=doc["customer_id"],
        source_id=doc["source_id"],
        producer_id="it-producer",
        received_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        request_id=doc.get("request_id"),
        observation_kind="gateway" if kind == "telemetry" else "billing",
        data=doc,
    )


def _hub_answers() -> bool:
    """A short, no-retry probe (the default client retries for minutes against a wedged hub)."""
    try:
        with EventHubProducerClient.from_connection_string(
            EVENTHUBS_CONNECTION, eventhub_name=HUB, retry_total=0, auth_timeout=HUB_PROBE_SECONDS
        ) as producer:
            return len(producer.get_partition_ids()) > 0
    except Exception:
        return False


async def _seed_policy(cosmos: Any, cfg: RuntimeConfig, domains: list[str]) -> None:
    """Grant the worker principal viewer on the trace's domains (the one derivation path)."""
    key = resolve_pseudonym_key(cfg.auth, env="local")
    principal = PrincipalPseudonymizer(key).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=normalize_tenant_id(WORKER_TENANT_ID),
        object_id=WORKER_OBJECT_ID,
        kind="service_principal",
    )
    policy = PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=tuple(domains),
        role_assignments=(
            PolicyRoleAssignment(
                assignment_id="ra-worker", role=Role.VIEWER, domain_ids=tuple(domains)
            ),
        ),
    )
    container = cosmos.get_database_client(cfg.store.database).get_container_client(
        cfg.auth.policy_container
    )
    await container.upsert_item(body=policy.model_dump(mode="json"))
    head = PolicyHead(customer_id=CUSTOMER, policy_version="it-1")
    await container.upsert_item(body=head.model_dump(mode="json"))


async def _publish(messages: list[HubMessage]) -> None:
    async with ClientLifetime() as lifetime:
        producer = create_eventhub_producer(
            Settings(env="local"), lifetime=lifetime, eventhub_name=HUB
        )
        for message in messages:
            batch = await producer.create_batch(partition_key=message.partition_key())
            batch.add(EventData(message.to_bytes()))
            await producer.send_batch(batch)


async def _land_in_process(cfg: RuntimeConfig, messages: list[HubMessage]) -> None:
    """The ingestion pipeline (same deps wiring as the role) without the hub."""
    ingestion = IngestionSettings().model_copy(update={"cosmos_database": cfg.store.database})
    start = datetime.now(UTC)
    raws = [
        RawMessage(
            body=m.to_bytes(),
            partition_id="0",
            offset=str(i),
            sequence_number=i,
            enqueued_time=start + timedelta(seconds=i),
        )
        for i, m in enumerate(messages)
    ]
    async with ClientLifetime() as lifetime:
        deps = await build_pipeline_deps(cfg.settings, lifetime=lifetime, ingestion=ingestion)
        await process_batch(raws, deps, ingestion)


async def _count(cosmos: Any, database: str, container: str, where: str = "1=1") -> int:
    proxy = cosmos.get_database_client(database).get_container_client(container)
    # Only fixed clause text from this module is interpolated.
    query = f"SELECT VALUE COUNT(1) FROM c WHERE {where}"
    rows = [row async for row in proxy.query_items(query=query)]
    return int(rows[0]) if rows else 0


@pytest.mark.parametrize(
    ("mode", "roles"),
    [
        ("hub", ("ingestion", "projections", "aggregates")),
        ("seeded", ("projections", "aggregates")),
    ],
)
async def test_pushed_sandbox_events_reach_ledger_aggregates_and_catalog(
    mode: str, roles: tuple[str, ...], worker_env: dict[str, str]
) -> None:
    if mode == "hub" and not await asyncio.to_thread(_hub_answers):
        pytest.skip("Event Hubs emulator does not answer (this suite never restarts it): OPEN")
    telemetry, cost = sandbox_trace_bundle()
    messages = [_message(d, "telemetry") for d in telemetry] + [_message(c, "cost") for c in cost]
    cfg = RuntimeConfig.from_env()
    database = cfg.store.database
    domains = sorted({d["domain_id"] for d in telemetry if d.get("domain_id")})
    counts: dict[str, int] = {}
    states: dict[str, str] = {}
    supervisor = RoleSupervisor(role_factories(cfg, roles))
    runner: asyncio.Task[None] | None = None

    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime)
        try:
            await ensure_local_containers(cosmos, cfg.settings, database=database)
            await _seed_policy(cosmos, cfg, domains)
            if mode == "hub":
                await _publish(messages)
            else:
                await _land_in_process(cfg, messages)
            runner = asyncio.create_task(supervisor.run())

            deadline = time.monotonic() + WAIT_SECONDS
            for _ in range(WAIT_SECONDS // POLL_SECONDS):
                counts = {
                    "ledger": await _count(cosmos, database, "cost-ledger", "c.doc_type = 'entry'"),
                    "aggregates": await _count(cosmos, database, "aggregates"),
                    "catalog": await _count(cosmos, database, "catalog"),
                }
                if all(counts.values()) or time.monotonic() > deadline:
                    break
                await asyncio.sleep(POLL_SECONDS)
            states = {r["name"]: f"{r['state']}:{r['reason']}" for r in supervisor.snapshot()}
        finally:
            supervisor.request_shutdown()
            if runner is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(runner, timeout=120)
            with contextlib.suppress(Exception):
                await cosmos.delete_database(database)
            for name in (
                worker_env["NS_ARCHIVE_CONTAINER"],
                worker_env["NS_QUARANTINE_CONTAINER"],
                worker_env["NS_INGESTION_CHECKPOINT_CONTAINER"],
            ):
                with contextlib.suppress(Exception):
                    async with ContainerClient.from_connection_string(
                        worker_env["NS_BLOB_CONNECTION_STRING"], name
                    ) as blob:
                        await blob.delete_container()

    assert counts["ledger"] > 0, f"ledger empty; roles={states}"
    assert counts["aggregates"] > 0, f"aggregates empty; roles={states}"
    assert counts["catalog"] > 0, f"catalog empty; roles={states}"
    assert set(states) == set(roles)
