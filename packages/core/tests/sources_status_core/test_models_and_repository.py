"""PRP-139 item 3: the run status model, its two repositories and the classifier."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.sources_status import (
    ConnectorRunStatus,
    CosmosSourceStatusRepository,
    InMemorySourceStatusRepository,
    classify_failure,
)
from pydantic import ValidationError

CUSTOMER = "contoso"
T1 = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 21, 11, 0, tzinfo=UTC)


def status(**over: Any) -> ConnectorRunStatus:
    body: dict[str, Any] = {
        "kind": "foundry_discovery",
        "state": "ok",
        "last_attempt_at": T1,
        "last_success_at": T1,
        "counts": {"records": 3},
    }
    body.update(over)
    return ConnectorRunStatus.model_validate(body)


class FakeContainer:
    """The three calls the repository makes, over a dict keyed by (partition, id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    async def read_item(self, *, item: str, partition_key: str) -> dict[str, Any]:
        row = self.rows.get((partition_key, item))
        if row is None:
            raise CosmosResourceNotFoundError(message="gone")
        return row

    async def upsert_item(self, *, body: dict[str, Any]) -> dict[str, Any]:
        self.rows[(body["customer_id"], body["id"])] = body
        return body

    async def query_items(
        self, sql: str, *, parameters: list[dict[str, Any]], partition_key: str
    ) -> AsyncIterator[dict[str, Any]]:
        for (partition, _), row in sorted(self.rows.items()):
            if partition == partition_key and row["doc_type"] == parameters[0]["value"]:
                yield row


def test_reason_and_count_names_must_be_codes() -> None:
    with pytest.raises(ValidationError):
        status(reason="https://example.test/x")
    with pytest.raises(ValidationError):
        status(counts={"project one": 1})
    with pytest.raises(ValidationError):
        status(counts={"records": -1})
    with pytest.raises(ValidationError):
        status(state="exploded")


def test_a_serialized_status_holds_no_guid_or_url() -> None:
    dumped = status(reason="source_access_denied").model_dump_json()
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", dumped)
    assert "http" not in dumped


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("failed:ForbiddenError", "source_access_denied"),
        ("failed:UnauthorizedError", "source_access_denied"),
        ("poll_failed:forbidden", "source_access_denied"),
        ("poll_failed:unauthorized", "source_access_denied"),
        ("failed:DependencyTransientError", None),
        ("read_failed", None),
    ],
)
def test_provider_401_and_403_map_to_source_access_denied(text: str, expected: str | None) -> None:
    assert classify_failure(text) == expected


async def test_in_memory_record_carries_the_last_success_forward() -> None:
    repo = InMemorySourceStatusRepository()
    await repo.record(CUSTOMER, status())
    failed = await repo.record(
        CUSTOMER,
        status(
            state="failed", reason="source_access_denied", last_success_at=None, last_attempt_at=T2
        ),
    )
    assert failed.last_success_at == T1
    assert failed.last_attempt_at == T2
    stored = await repo.get(CUSTOMER, "foundry_discovery")
    assert stored is not None and stored.state == "failed" and stored.last_success_at == T1


async def test_a_new_success_replaces_the_carried_time() -> None:
    repo = InMemorySourceStatusRepository()
    await repo.record(CUSTOMER, status())
    again = await repo.record(CUSTOMER, status(last_success_at=T2, last_attempt_at=T2))
    assert again.last_success_at == T2


async def test_statuses_are_per_customer_and_listed_by_kind() -> None:
    repo = InMemorySourceStatusRepository()
    await repo.record(CUSTOMER, status(kind="gateway_poll"))
    await repo.record(CUSTOMER, status(kind="billing_export"))
    await repo.record("fabrikam", status())
    assert [s.kind for s in await repo.list(CUSTOMER)] == ["billing_export", "gateway_poll"]
    assert await repo.get("fabrikam", "gateway_poll") is None


async def test_cosmos_rows_use_the_admin_config_container_shape() -> None:
    container = FakeContainer()
    repo = CosmosSourceStatusRepository(container)  # type: ignore[arg-type]
    await repo.record(CUSTOMER, status(kind="billing_export"))
    row = container.rows[(CUSTOMER, "connector_run_status:billing_export")]
    assert row["doc_type"] == "connector_run_status"
    assert row["customer_id"] == CUSTOMER
    assert row["kind"] == "connector_run_status"
    assert [s.kind for s in await repo.list(CUSTOMER)] == ["billing_export"]
    assert await repo.get(CUSTOMER, "foundry_discovery") is None


async def test_cosmos_carries_the_last_success_and_ignores_other_doc_types() -> None:
    container = FakeContainer()
    repo = CosmosSourceStatusRepository(container)  # type: ignore[arg-type]
    await repo.record(CUSTOMER, status())
    await repo.record(
        CUSTOMER, status(state="failed", reason="source_unreachable", last_success_at=None)
    )
    stored = await repo.get(CUSTOMER, "foundry_discovery")
    assert stored is not None and stored.last_success_at == T1
    container.rows[(CUSTOMER, "admin_config:other")] = {
        "id": "admin_config:other",
        "doc_type": "admin_config",
        "customer_id": CUSTOMER,
    }
    assert len(await repo.list(CUSTOMER)) == 1


async def test_a_store_outage_is_a_transient_error_without_driver_text() -> None:
    class Broken(FakeContainer):
        async def upsert_item(self, *, body: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("AccountKey=hunter2")

    repo = CosmosSourceStatusRepository(Broken())  # type: ignore[arg-type]
    with pytest.raises(DependencyTransientError) as raised:
        await repo.record(CUSTOMER, status())
    assert "hunter2" not in str(raised.value)
