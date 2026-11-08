"""Catalog latency over Cosmos (PRP-10 item 13): MEASURED, never asserted.

Emulator mode (``-m integration``, needs ``docker compose up -d --wait cosmos``): the same scoped
workloads as the in-memory run, over ``CosmosCatalogRepository`` against the vNext emulator, with
the sandbox profile loaded into a throwaway database/container that is deleted afterwards.
Result: ``temp/catalog_latency/p95-emulator.json``. The emulator has no RU accounting and no
range/composite indexes, so this is bounded feasibility (G12), not a live claim.

Live mode (``-m live``): refuses unless ``NS_LIVE_APPROVED=1`` and the endpoint/database env vars
are set (see ``live_guard``). Entra auth through ``DefaultAzureCredential`` only; no keys. It
creates and deletes a throwaway container in an existing database (Entra data-plane roles
cannot create databases). Do not run without operator approval.
"""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any

import pytest
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from neurosphere_core.catalog import PartitionKeyShape
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository, create_catalog_container
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings

from .harness import RESULT_DIR, check_and_record, make_world, measure
from .live_guard import ENV_DATABASE, ENV_ENDPOINT, live_refusal

EMULATOR_LABEL = (
    "Cosmos vNext emulator, bounded feasibility (G12), not a live claim: "
    "no RU accounting, no range/composite indexes"
)
LIVE_LABEL = "live Cosmos NoSQL account, Entra auth, operator-approved run"
SHAPE = PartitionKeyShape.FLAT_DOMAIN


async def _run(container: Any, label: str, disclaimer: str) -> dict[str, Any]:
    world, all_domains, agents = make_world()
    repo = CosmosCatalogRepository(container, SHAPE)
    return await measure(repo, world, all_domains, agents, label=label, disclaimer=disclaimer)


@pytest.mark.integration
async def test_emulator_scoped_latency_is_measured_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    # The emulator ignores the key; any base64 string works (same as the repo conformance tests).
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    db_name = f"ns_catalog_latency_{uuid.uuid4().hex[:10]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        database = await client.create_database_if_not_exists(db_name)
        try:
            container = await create_catalog_container(database, "catalog", SHAPE)
            result = await _run(
                container,
                EMULATOR_LABEL,
                "Measured against the Cosmos vNext emulator over loopback. Not evidence for the "
                "PRP-10 p95 target; live gate G03 is OPEN. Search uses the fixture index "
                "(Azure AI Search is not in the emulator).",
            )
        finally:
            await client.delete_database(db_name)
    check_and_record(result, EMULATOR_LABEL, RESULT_DIR / "p95-emulator.json")


@pytest.mark.live
async def test_live_scoped_latency_requires_operator_approval() -> None:
    reason = live_refusal(os.environ)
    if reason is not None:
        pytest.skip(reason)
    container_id = f"catalog_latency_{uuid.uuid4().hex[:10]}"
    async with DefaultAzureCredential() as credential:
        async with CosmosClient(os.environ[ENV_ENDPOINT], credential) as client:
            database = client.get_database_client(os.environ[ENV_DATABASE])
            container = await create_catalog_container(database, container_id, SHAPE)
            try:
                result = await _run(
                    container,
                    LIVE_LABEL,
                    "Operator-approved live run; compare with the emulator run for G12 deltas.",
                )
            finally:
                await database.delete_container(container_id)
    check_and_record(result, LIVE_LABEL, RESULT_DIR / "p95-live.json")
