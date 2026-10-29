"""CosmosGatewayStore against the compose emulator.

Run: ``docker compose up -d --wait`` then ``pytest -m integration tests/integration/gateway``.
Each test gets its own container (deleted afterwards). The emulator has no auth or RU accounting;
this proves create-only, ETag-conditional replace, hierarchical-key isolation and whole-snapshot
inventory replacement only. Endpoint is 127.0.0.1 (localhost resolves to ::1 and breaks 8081).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.gateway import (
    ApiEntry,
    CosmosGatewayStore,
    GatewayInventory,
    GatewayRegistration,
    GatewayStore,
    create_gateway_container,
    gateway_id_for,
)
from neurosphere_core.gateway.cosmos_store import GATEWAY_PARTITION_KEY_PATHS

pytestmark = pytest.mark.integration

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:hr"
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
ARM = (
    "/subscriptions/11111111-2222-4333-8444-555555555555/resourceGroups/rg"
    "/providers/Microsoft.ApiManagement/service/apim-it-{n}"
)


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_gateway_it")


@pytest_asyncio.fixture
async def container(database: DatabaseProxy) -> AsyncIterator[ContainerProxy]:
    created = await create_gateway_container(database, f"gateways_{uuid.uuid4().hex[:10]}")
    try:
        yield created
    finally:
        await database.delete_container(created.id)


def _registration(n: int, domain: str = DOMAIN) -> GatewayRegistration:
    arm = ARM.format(n=n)
    return GatewayRegistration(
        id=gateway_id_for(CUSTOMER, domain, arm),
        customer_id=CUSTOMER,
        domain_id=domain,
        cloud="commercial",
        arm_resource_id=arm,
        name=f"apim-it-{n}",
        tier="standard_v2",
        created_at=T0 + timedelta(seconds=n),
        updated_at=T0 + timedelta(seconds=n),
        registered_by="pseudo-it",
    )


async def test_container_uses_the_hierarchical_key(container: ContainerProxy) -> None:
    key = (await container.read())["partitionKey"]
    assert key["paths"] == list(GATEWAY_PARTITION_KEY_PATHS)
    assert key["kind"] == "MultiHash"


async def test_create_get_duplicate_and_isolation(container: ContainerProxy) -> None:
    store = CosmosGatewayStore(container)
    assert isinstance(store, GatewayStore)
    created = await store.create(_registration(1))
    assert created.etag
    assert await store.get(CUSTOMER, DOMAIN, created.id) == created
    assert await store.get(CUSTOMER, OTHER_DOMAIN, created.id) is None
    with pytest.raises(StaleVersionError) as info:
        await store.create(_registration(1))
    assert info.value.reason == "gateway_already_registered"


async def test_replace_is_etag_conditional(container: ContainerProxy) -> None:
    store = CosmosGatewayStore(container)
    created = await store.create(_registration(1))
    assert created.etag is not None
    saved = await store.replace(
        created.model_copy(update={"last_sync_status": "ok"}), if_match=created.etag
    )
    assert saved.etag != created.etag
    assert saved.last_sync_status == "ok"
    with pytest.raises(StaleVersionError) as info:
        await store.replace(created, if_match=created.etag)
    assert info.value.reason == "gateway_modified"


async def test_list_pages_newest_first_within_the_partition(container: ContainerProxy) -> None:
    store = CosmosGatewayStore(container)
    for n in (1, 2, 3):
        await store.create(_registration(n))
    await store.create(_registration(4, OTHER_DOMAIN))
    first = await store.list(CUSTOMER, DOMAIN, limit=2)
    assert [g.name for g in first.items] == ["apim-it-3", "apim-it-2"]
    assert first.next_cursor is not None
    second = await store.list(CUSTOMER, DOMAIN, cursor=first.next_cursor, limit=2)
    assert [g.name for g in second.items] == ["apim-it-1"]
    assert second.next_cursor is None


async def test_inventory_is_replaced_and_not_listed_as_a_gateway(
    container: ContainerProxy,
) -> None:
    store = CosmosGatewayStore(container)
    reg = await store.create(_registration(1))
    await store.put_inventory(
        CUSTOMER,
        DOMAIN,
        GatewayInventory(gateway_id=reg.id, taken_at=T0, apis=[ApiEntry(id="a"), ApiEntry(id="b")]),
    )
    await store.put_inventory(
        CUSTOMER,
        DOMAIN,
        GatewayInventory(
            gateway_id=reg.id, taken_at=T0 + timedelta(hours=1), apis=[ApiEntry(id="c")]
        ),
    )
    got = await store.get_inventory(CUSTOMER, DOMAIN, reg.id)
    assert got is not None
    assert [a.id for a in got.apis] == ["c"]
    assert await store.get_inventory(CUSTOMER, OTHER_DOMAIN, reg.id) is None
    listing = await store.list(CUSTOMER, DOMAIN)
    assert [g.id for g in listing.items] == [reg.id]
