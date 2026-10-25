"""Production wiring: containers are created only for NS_ENV=local; prices are never invented.

No real clients: SDK constructors are replaced with in-memory fakes.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger import TokenCounts
from neurosphere_workers.ingestion import wiring
from neurosphere_workers.ingestion.protocols import ArchiveSink, LedgerSink, QuarantineSink
from neurosphere_workers.ingestion.wiring import (
    LedgerSettings,
    ensure_blob_container,
    ensure_cosmos_containers,
    load_price_table,
)
from neurosphere_workers.projections.outbox import CostLedgerSink


class FakeBlob:
    def __init__(self, present: bool = False) -> None:
        self.present = present
        self.created = 0

    async def create_container(self) -> None:
        if self.present:
            raise ResourceExistsError("exists")
        self.present = True
        self.created += 1

    async def exists(self) -> bool:
        return self.present

    async def close(self) -> None:
        return None


class FakeContainerProxy:
    def __init__(self, present: bool) -> None:
        self._present = present

    async def read(self) -> dict[str, Any]:
        if not self._present:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        return {}


class FakeDatabase:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()
        self.created: list[str] = []

    async def create_container_if_not_exists(self, id: str, partition_key: Any) -> None:
        assert partition_key.path == "/customer_id"
        self.existing.add(id)
        self.created.append(id)

    def get_container_client(self, name: str) -> FakeContainerProxy:
        return FakeContainerProxy(name in self.existing)


class FakeCosmos:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_created = False

    async def create_database_if_not_exists(self, name: str) -> None:
        self.database_created = True

    def get_database_client(self, name: str) -> FakeDatabase:
        return self.database

    async def close(self) -> None:
        return None


class Quarantine:
    async def write(self, record: Any) -> None:
        return None


class Archive:
    async def write(self, event: Any) -> None:
        return None


def patch_clients(
    monkeypatch: pytest.MonkeyPatch, database: FakeDatabase, blobs: dict[str, FakeBlob]
) -> FakeCosmos:
    cosmos = FakeCosmos(database)
    monkeypatch.setattr(wiring, "create_cosmos_client", lambda *a, **k: cosmos)
    monkeypatch.setattr(
        wiring,
        "_blob_container_client",
        lambda settings, name, account, lifetime: blobs.setdefault(name, FakeBlob()),
    )
    monkeypatch.setattr(wiring, "create_quarantine_container", lambda *a, **k: object())
    monkeypatch.setattr(wiring, "BlobQuarantineSink", lambda container: Quarantine())
    monkeypatch.setattr(wiring, "create_archive_sink", lambda *a, **k: Archive())
    return cosmos


# -- price table ---------------------------------------------------------------------------


def test_no_price_file_gives_empty_table_and_unresolved_estimates() -> None:
    table = load_price_table(None)
    assert table.versions == []
    estimate = table.estimate_cost(
        "azure_openai", "gpt-x", None, TokenCounts(input=10, output=10), date(2026, 10, 1)
    )
    assert estimate.resolved is False
    assert estimate.amount is None
    assert estimate.price_version_id is None


def test_price_file_is_loaded(tmp_path: Path) -> None:
    sheet = {
        "versions": [
            {
                "price_version_id": "synthetic-test-v1",
                "effective_date": "2026-10-01",
                "currency": "USD",
                "source": "synthetic test sheet",
                "rates": [
                    {
                        "provider": "azure_openai",
                        "model": "gpt-x",
                        "rate": {"input": "1.0", "output": "2.0"},
                    }
                ],
            }
        ]
    }
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(sheet), encoding="utf-8")
    table = load_price_table(path)
    estimate = table.estimate_cost(
        "azure_openai", "gpt-x", None, TokenCounts(input=1_000_000, output=0), date(2026, 10, 2)
    )
    assert estimate.resolved is True
    assert estimate.price_version_id == "synthetic-test-v1"


# -- container policy ----------------------------------------------------------------------


async def test_blob_container_created_locally_and_exists_is_fine() -> None:
    fresh = FakeBlob()
    await ensure_blob_container(fresh, "ns-archive", create=True)
    assert fresh.created == 1
    await ensure_blob_container(fresh, "ns-archive", create=True)  # ResourceExistsError swallowed
    assert fresh.created == 1


class RacingDatabase(FakeDatabase):
    """Another role creates ``cost-ledger`` between the existence check and the create."""

    async def create_container_if_not_exists(self, id: str, partition_key: Any) -> None:
        if id == "cost-ledger":
            self.existing.add(id)
            raise CosmosResourceExistsError(status_code=409, message="already exists")
        await super().create_container_if_not_exists(id, partition_key)


async def test_cosmos_create_race_409_is_success_locally() -> None:
    database = RacingDatabase()
    await ensure_cosmos_containers(database, ["cost-ledger", "outbox"], create=True)
    assert "cost-ledger" in database.existing
    assert database.created == ["outbox"], "the loop continued past the 409"


async def test_blob_container_missing_outside_local_is_a_clear_error() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        await ensure_blob_container(FakeBlob(), "ns-archive", create=False)
    assert "ns-archive" in str(info.value)
    assert "IaC" in str(info.value)


async def test_cosmos_containers_missing_outside_local_is_a_clear_error() -> None:
    database = FakeDatabase({"a"})
    with pytest.raises(InvalidSchemaError) as info:
        await ensure_cosmos_containers(database, ["a", "b"], create=False)
    assert "'b'" in str(info.value)
    assert database.created == []  # never created outside local


async def test_cosmos_containers_created_locally() -> None:
    database = FakeDatabase()
    await ensure_cosmos_containers(database, ["a", "b"], create=True)
    assert database.created == ["a", "b"]


# -- build_pipeline_deps -------------------------------------------------------------------


async def test_local_build_creates_everything_and_uses_empty_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase()
    blobs: dict[str, FakeBlob] = {}
    cosmos = patch_clients(monkeypatch, database, blobs)
    async with ClientLifetime() as lifetime:
        deps = await wiring.build_pipeline_deps(Settings(env="local"), lifetime=lifetime)
    assert cosmos.database_created
    assert set(database.created) == {
        "ingestion-accepted",
        "ingestion-watermarks",
        "cost-ledger",
        "outbox",
        "outbox-checkpoints",
    }
    assert set(blobs) == {"ns-archive", "ns-quarantine", "ns-ingestion-checkpoints"}
    assert all(b.created == 1 for b in blobs.values())
    assert deps.cloud == "commercial"
    assert isinstance(deps.quarantine, QuarantineSink)
    assert isinstance(deps.archive, ArchiveSink)
    assert isinstance(deps.ledger, CostLedgerSink)
    assert isinstance(deps.ledger, LedgerSink)
    assert deps.ledger._prices.versions == []  # type: ignore[attr-defined]


async def test_non_local_with_missing_blob_container_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_clients(monkeypatch, FakeDatabase(), {})
    settings = Settings(env="prod", cloud=CloudName.GOVERNMENT)
    async with ClientLifetime() as lifetime:
        with pytest.raises(InvalidSchemaError) as info:
            await wiring.build_pipeline_deps(settings, lifetime=lifetime)
    assert "does not exist" in str(info.value)


async def test_non_local_with_missing_cosmos_container_fails_and_creates_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase({"ingestion-accepted"})
    blobs = {
        "ns-archive": FakeBlob(True),
        "ns-quarantine": FakeBlob(True),
        "ns-ingestion-checkpoints": FakeBlob(True),
    }
    cosmos = patch_clients(monkeypatch, database, blobs)
    settings = Settings(env="prod", cloud=CloudName.GOVERNMENT)
    async with ClientLifetime() as lifetime:
        with pytest.raises(InvalidSchemaError) as info:
            await wiring.build_pipeline_deps(settings, lifetime=lifetime)
    assert "ingestion-watermarks" in str(info.value)
    assert database.created == []
    assert not cosmos.database_created
    assert all(b.created == 0 for b in blobs.values())


async def test_non_local_with_everything_provisioned_builds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    names = {"ingestion-accepted", "ingestion-watermarks", "cost-ledger", "outbox"}
    database = FakeDatabase(names | {"outbox-checkpoints"})
    blobs = {n: FakeBlob(True) for n in ("ns-archive", "ns-quarantine", "ns-ingestion-checkpoints")}
    patch_clients(monkeypatch, database, blobs)
    settings = Settings(env="prod", cloud=CloudName.GOVERNMENT)
    async with ClientLifetime() as lifetime:
        deps = await wiring.build_pipeline_deps(
            settings, lifetime=lifetime, ledger=LedgerSettings(price_table_file=None)
        )
    assert deps.cloud == "government"
    assert database.created == []
