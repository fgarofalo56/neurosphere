"""The container registry equals the wire contract and every core store's in-module constants.

Stores that live in ``services/`` (reports, copilot, ingestion and ledger wiring) are pinned by
``services/api/tests/runtime_api/test_registry_parity.py``; core tests never import services.
"""

from __future__ import annotations

import inspect
from typing import Any, Literal

import pytest
from azure.cosmos.exceptions import CosmosResourceExistsError
from neurosphere_core.actions import cosmos_store as actions_store
from neurosphere_core.aggregates import cosmos as aggregates_store
from neurosphere_core.audit import cosmos_store as audit_store
from neurosphere_core.auth.revocation import cosmos_store as revocation_store
from neurosphere_core.auth.scope import cosmos_repository as policy_store
from neurosphere_core.catalog.partitioning import PartitionKeyShape, partition_key_paths
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.deploy.register import cosmos_store as register_store
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.lifecycle.rules import AUDIT_CONTAINERS
from neurosphere_core.mcp import cosmos_store as mcp_store
from neurosphere_core.stores import (
    CONTAINERS,
    DEFAULT_DATABASE,
    TTL_PER_ITEM,
    ContainerSpec,
    container_spec,
    ensure_local_containers,
)

#: PRP-29 wire contract "Cosmos containers", with the item 1 partition-key confirmations:
#: ``price_snapshots`` /snapshot_id (was /source), ``hitl_decisions`` /review_item_id (was
#: /customer_id,/domain_id) and ``catalog_review_queue`` /customer_id,/domain_id (was /domain).
WIRE_CONTRACT: dict[str, tuple[str, ...]] = {
    "policy": ("/customer_id",),
    "revocations": ("/principal_id",),
    "catalog": ("/domain",),
    "aggregates": ("/customer_id",),
    "cost-ledger": ("/customer_id",),
    "outbox": ("/customer_id",),
    "outbox-checkpoints": ("/customer_id",),
    "ingestion-accepted": ("/customer_id",),
    "ingestion-watermarks": ("/customer_id",),
    "action_intents": ("/customer_id", "/domain_id"),
    "action_execution_control": ("/customer_id",),
    "audit": ("/chain_id",),
    "audit_tail": ("/chain_id",),
    "copilot_conversations": ("/owner",),
    "reports": ("/customer_id", "/domain_id"),
    "mcp_servers": ("/id",),
    "deploy_register": ("/deployment_id",),
    "recommendations": ("/customer_id", "/domain_id"),
    "evaluation_runs": ("/customer_id", "/domain_id"),
    "evaluation_results": ("/customer_id", "/domain_id"),
    "price_snapshots": ("/snapshot_id",),
    "hitl_items": ("/customer_id", "/domain_id"),
    "hitl_decisions": ("/review_item_id",),
    "catalog_review_queue": ("/customer_id", "/domain_id"),
    "lifecycle_requests": ("/customer_id",),
    "lifecycle_holds": ("/customer_id",),
    "lifecycle_mappings": ("/customer_id",),
}


def _paths(name: str) -> tuple[str, ...]:
    return container_spec(name).partition_key_paths


def test_registry_is_exactly_the_wire_contract() -> None:
    assert {s.name: s.partition_key_paths for s in CONTAINERS} == WIRE_CONTRACT
    assert DEFAULT_DATABASE == "neurosphere"


def test_kinds_and_ttls() -> None:
    for spec in CONTAINERS:
        assert spec.kind == ("MultiHash" if len(spec.partition_key_paths) > 1 else "Hash")
    ttl = {s.name for s in CONTAINERS if s.default_ttl is not None}
    assert ttl == {"revocations", "copilot_conversations"}
    assert container_spec("revocations").default_ttl == TTL_PER_ITEM


def test_actions_store_constants() -> None:
    intents = _paths(actions_store.DEFAULT_INTENT_CONTAINER)
    assert intents == actions_store.INTENT_PARTITION_KEY_PATHS
    assert _paths(actions_store.DEFAULT_CONTROL_CONTAINER) == (
        actions_store.CONTROL_PARTITION_KEY_PATH,
    )


def test_identity_store_constants() -> None:
    assert _paths(policy_store.DEFAULT_POLICY_CONTAINER) == ("/customer_id",)
    assert _paths(revocation_store.DEFAULT_REVOCATION_CONTAINER) == (
        revocation_store.PARTITION_KEY_PATH,
    )


def test_audit_mcp_aggregates_and_register_constants() -> None:
    for name in sorted(AUDIT_CONTAINERS):
        assert _paths(name) == (audit_store.PARTITION_KEY_PATH,)
    assert _paths(mcp_store.DEFAULT_MCP_SERVER_CONTAINER) == (mcp_store.PARTITION_KEY_PATH,)
    assert _paths("aggregates") == (aggregates_store.PARTITION_KEY_PATH,)
    assert _paths("deploy_register") == (register_store.PARTITION_KEY_PATH,)


def test_catalog_uses_the_repository_default_shape() -> None:
    default = inspect.signature(CosmosCatalogRepository.__init__).parameters["shape"].default
    assert default is PartitionKeyShape.FLAT_DOMAIN
    assert _paths("catalog") == partition_key_paths(PartitionKeyShape.FLAT_DOMAIN)


def test_sdk_partition_key_definitions() -> None:
    hierarchical = container_spec("action_intents").partition_key()
    assert hierarchical["paths"] == ["/customer_id", "/domain_id"]
    assert hierarchical["kind"] == "MultiHash"
    flat = container_spec("policy").partition_key()
    assert flat["paths"] == ["/customer_id"]
    assert flat["kind"] == "Hash"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "partition_key_paths": ("/a",)},
        {"name": "x", "partition_key_paths": ()},
        {"name": "x", "partition_key_paths": ("a",)},
        {"name": "x", "partition_key_paths": ("/a", "/b", "/c", "/d")},
        {"name": "x", "partition_key_paths": ("/a",), "default_ttl": 0},
    ],
)
def test_invalid_specs_are_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ContainerSpec(owner="tests", **kwargs)


class _FakeDatabase:
    def __init__(self) -> None:
        self.created: list[tuple[str, Any, dict[str, Any]]] = []

    async def create_container_if_not_exists(self, id: str, partition_key: Any, **kw: Any) -> Any:
        self.created.append((id, partition_key, kw))
        return self


class _FakeClient:
    def __init__(self, database: _FakeDatabase | None = None) -> None:
        self.databases: list[str] = []
        self.database = database or _FakeDatabase()

    async def create_database_if_not_exists(self, id: str) -> _FakeDatabase:
        self.databases.append(id)
        return self.database

    def get_database_client(self, database: str) -> _FakeDatabase:
        return self.database


async def test_ensure_local_containers_creates_every_container_idempotently() -> None:
    client = _FakeClient()
    names = await ensure_local_containers(client, Settings(env="local"))
    assert names == tuple(s.name for s in CONTAINERS)
    assert client.databases == ["neurosphere"]
    created = {name: (pk, kw) for name, pk, kw in client.database.created}
    assert created["copilot_conversations"][1] == {"default_ttl": TTL_PER_ITEM}
    assert created["reports"][0]["kind"] == "MultiHash"
    again = await ensure_local_containers(client, Settings(env="local"), database="other")
    assert again == names
    assert client.databases == ["neurosphere", "other"]


@pytest.mark.parametrize("env", ["dev", "test", "staging", "prod"])
async def test_ensure_local_containers_refuses_outside_local(
    env: Literal["dev", "test", "staging", "prod"],
) -> None:
    client = _FakeClient()
    settings = Settings(env=env, cloud=CloudName.COMMERCIAL)
    with pytest.raises(InvalidSchemaError) as caught:
        await ensure_local_containers(client, settings)
    assert caught.value.reason == "config"
    assert client.databases == []
    assert client.database.created == []


class _RacingDatabase(_FakeDatabase):
    async def create_container_if_not_exists(self, id: str, partition_key: Any, **kw: Any) -> Any:
        self.created.append((id, partition_key, kw))
        raise CosmosResourceExistsError(status_code=409, message="Conflict")


class _RacingClient(_FakeClient):
    def __init__(self) -> None:
        super().__init__(_RacingDatabase())

    async def create_database_if_not_exists(self, id: str) -> _FakeDatabase:
        self.databases.append(id)
        raise CosmosResourceExistsError(status_code=409, message="Conflict")

    def get_database_client(self, database: str) -> _FakeDatabase:
        return self.database


async def test_ensure_local_containers_treats_409_as_success() -> None:
    client = _RacingClient()
    names = await ensure_local_containers(client, Settings(env="local"))
    assert names == tuple(s.name for s in CONTAINERS)
    assert len(client.database.created) == len(CONTAINERS)
