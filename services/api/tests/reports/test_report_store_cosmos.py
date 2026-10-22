"""CosmosReportStore against the compose emulator (never runs in CI: ``integration`` marker).

Run: ``docker compose up -d --wait`` then ``pytest -m integration services/api/tests/reports``.
Emulator limits (G12): no auth, no RU accounting. Passing says nothing about RBAC or RU cost.
"""

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azure.cosmos.aio import ContainerProxy, DatabaseProxy
from neurosphere_api.reports import (
    REPORT_PARTITION_KEY_PATHS,
    CosmosReportStore,
    Publication,
    StoredReport,
    create_report_container,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import StaleVersionError

pytestmark = pytest.mark.integration

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
OWNER = "commercial:contoso:entra:person:psn_0123456789abcdef"
SHARED_WITH = "commercial:contoso:entra:person:psn_fedcba9876543210"
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _emulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://localhost:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseProxy]:
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        yield await client.create_database_if_not_exists("ns_reports_it")


@pytest_asyncio.fixture
async def container(database: DatabaseProxy) -> AsyncIterator[ContainerProxy]:
    created = await create_report_container(database, f"reports_{uuid.uuid4().hex[:10]}")
    try:
        yield created
    finally:
        await database.delete_container(created.id)


def _report(n: int, **update: object) -> StoredReport:
    base = StoredReport(
        id=f"rpt-{n:04d}",
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        owner=OWNER,
        title=f"Report {n}",
        chart_plan={"schema_version": "1.0.0"},
        query_spec={"operation": "list", "entity": "agent"},
        created_at=T0 + timedelta(minutes=n),
        updated_at=T0 + timedelta(minutes=n),
    )
    return base.model_copy(update=update)


async def test_container_uses_the_hierarchical_key(container: ContainerProxy) -> None:
    key = (await container.read())["partitionKey"]
    assert key["paths"] == list(REPORT_PARTITION_KEY_PATHS)
    assert key["kind"] == "MultiHash"


async def test_create_get_replace_delete_with_etags(container: ContainerProxy) -> None:
    store = CosmosReportStore(container)
    created = await store.create(_report(1))
    assert created.etag
    fetched = await store.get(CUSTOMER, DOMAIN, "rpt-0001")
    assert fetched == created
    updated = await store.replace(
        created.model_copy(update={"title": "New"}), if_match=created.etag
    )
    assert updated.etag != created.etag
    with pytest.raises(StaleVersionError):
        await store.replace(created, if_match=created.etag)
    with pytest.raises(StaleVersionError):
        await store.delete(CUSTOMER, DOMAIN, "rpt-0001", if_match=created.etag)
    await store.delete(CUSTOMER, DOMAIN, "rpt-0001", if_match=updated.etag or "")
    assert await store.get(CUSTOMER, DOMAIN, "rpt-0001") is None


async def test_list_filters_by_visibility_and_publication(container: ContainerProxy) -> None:
    store = CosmosReportStore(container)
    await store.create(_report(1))
    await store.create(_report(2, shares=[SHARED_WITH]))
    await store.create(_report(3, publication=Publication(state="approved")))
    await store.create(_report(4, owner="commercial:contoso:entra:person:psn_other"))
    mine = await store.list(CUSTOMER, DOMAIN, visible_to=OWNER)
    assert [r.id for r in mine.items] == ["rpt-0003", "rpt-0002", "rpt-0001"]
    shared = await store.list(CUSTOMER, DOMAIN, visible_to=SHARED_WITH)
    assert [r.id for r in shared.items] == ["rpt-0003", "rpt-0002"]
    approved = await store.list(CUSTOMER, DOMAIN, publication_state="approved")
    assert [r.id for r in approved.items] == ["rpt-0003"]
    first = await store.list(CUSTOMER, DOMAIN, limit=2)
    assert first.next_cursor is not None
    second = await store.list(CUSTOMER, DOMAIN, limit=2, cursor=first.next_cursor)
    assert [r.id for r in first.items + second.items] == [
        "rpt-0004",
        "rpt-0003",
        "rpt-0002",
        "rpt-0001",
    ]
