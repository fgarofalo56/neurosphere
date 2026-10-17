"""CosmosCatalogRepository against the compose emulator (`docker compose up -d --wait`).

Runs the same conformance checks as the in-memory unit tests. Emulator limits (PRP-05 C4):
no auth enforcement, RU accounting or index tuning; passing here says nothing about RBAC, RU
cost or real-account indexing (live gate G03 / PRP-13).
"""

from __future__ import annotations

import base64
import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.capabilities import default_matrix
from neurosphere_core.catalog import CatalogRepository, PartitionKeyShape, partition_key_paths
from neurosphere_core.catalog import resolve_shape as resolve
from neurosphere_core.catalog.protocol import EdgeObservation
from neurosphere_core.catalog.repo.backend import DocPreconditionFailedError, Query, ScopeFilter
from neurosphere_core.catalog.repo.cosmos import (
    CosmosBackend,
    CosmosCatalogRepository,
    create_catalog_container,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors.taxonomy import StaleVersionError

pytestmark = pytest.mark.integration

_HELPER = Path(__file__).resolve().parents[3] / "packages/core/tests/catalog/repo_conformance.py"
SHAPES = [PartitionKeyShape.FLAT_DOMAIN, PartitionKeyShape.TENANT_DOMAIN_SHARD]


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("catalog_repo_conformance", _HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _load_helper()


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_catalog_repo_it")


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.value)
@pytest.mark.parametrize("name", list(helper.CHECKS))
async def test_cosmos_conformance(
    database: DatabaseProxy, name: str, shape: PartitionKeyShape
) -> None:
    container = await create_catalog_container(
        database, f"cat_{shape.value}_{uuid.uuid4().hex[:8]}", shape
    )
    try:
        repo = CosmosCatalogRepository(container, shape)
        assert isinstance(repo, CatalogRepository)
        await helper.CHECKS[name](repo, f"t{uuid.uuid4().hex[:10]}")
    finally:
        await database.delete_container(container.id)


async def test_container_key_follows_resolve_shape(database: DatabaseProxy) -> None:
    # Current matrix: hierarchical keys are unverified, so the default request falls back to flat.
    resolution = resolve(PartitionKeyShape.TENANT_DOMAIN_SHARD, "commercial", default_matrix())
    assert resolution.fell_back
    flat = await create_catalog_container(
        database, f"cat_resolved_{uuid.uuid4().hex[:8]}", resolution.shape
    )
    forced = await create_catalog_container(
        database, f"cat_forced_{uuid.uuid4().hex[:8]}", PartitionKeyShape.TENANT_DOMAIN_SHARD
    )
    try:
        flat_key = (await flat.read())["partitionKey"]
        forced_key = (await forced.read())["partitionKey"]
        assert flat_key["paths"] == list(partition_key_paths(PartitionKeyShape.FLAT_DOMAIN))
        assert flat_key["kind"] == "Hash"
        assert forced_key["paths"] == list(
            partition_key_paths(PartitionKeyShape.TENANT_DOMAIN_SHARD)
        )
        assert forced_key["kind"] == "MultiHash"
    finally:
        await database.delete_container(flat.id)
        await database.delete_container(forced.id)


async def test_cosmos_precondition_failure_maps_to_stale_version(database: DatabaseProxy) -> None:
    shape = PartitionKeyShape.FLAT_DOMAIN
    container = await create_catalog_container(database, f"cat_412_{uuid.uuid4().hex[:8]}", shape)
    try:
        ns = f"t{uuid.uuid4().hex[:10]}"
        repo = CosmosCatalogRepository(container, shape)
        scope = helper.make_scope(ns, [helper.dom(ns, "a")])
        created = await repo.create_entity(scope, helper.agent(ns, "race", "a"))
        backend = CosmosBackend(container)
        rows = await backend.query(
            Query("entity", ScopeFilter("commercial", ns, None), 1, eq=(("ref", created.id),))
        )
        stored = dict(rows[0])
        await backend.replace(stored, stored["_etag"])  # winner changes the document ETag
        with pytest.raises(DocPreconditionFailedError):
            await backend.replace(stored, stored["_etag"])  # loser used the old Cosmos _etag
        # and through the repository: a second edit with the already-consumed contract ETag
        await repo.update_entity(
            scope, helper.agent(ns, "race", "a", display_name="X"), created.etag.root
        )
        with pytest.raises(StaleVersionError):
            await repo.update_entity(
                scope, helper.agent(ns, "race", "a", display_name="Y"), created.etag.root
            )
    finally:
        await database.delete_container(container.id)


async def test_observation_documents_hold_ids_only(database: DatabaseProxy) -> None:
    shape = PartitionKeyShape.FLAT_DOMAIN
    container = await create_catalog_container(database, f"cat_obs_{uuid.uuid4().hex[:8]}", shape)
    try:
        ns = f"t{uuid.uuid4().hex[:10]}"
        repo = CosmosCatalogRepository(container, shape)
        scope = helper.make_scope(ns, [helper.dom(ns, "a")])
        obs = helper.observation(ns, "o1", "e1", "a", "2026-10-01T00:00:00Z")
        assert await repo.record_observation(scope, obs) is True
        rows = await CosmosBackend(container).query(
            Query("observation", ScopeFilter("commercial", ns, None), 5)
        )
        assert len(rows) == 1
        assert set(rows[0]["body"]) == set(EdgeObservation.model_fields)
        assert rows[0]["body"]["evidence_ids"] == ["trace:o1"]
    finally:
        await database.delete_container(container.id)
