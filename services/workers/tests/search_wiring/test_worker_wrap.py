"""Worker catalog write-through (PRP-60 item 6): wrapped only for a supported Azure search."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.search.write_hook import IndexingCatalogRepository
from neurosphere_workers.runtime.search_wiring import WorkerSearchSettings, wrap_catalog_for_search

NS = "synthco"
ENTITY_ID = f"commercial:{NS}:foundry:agent:one"
SCOPE: Any = object()


class StubRepo:
    """Only ``create_entity`` is exercised; it returns the entity as a plain mapping."""

    async def create_entity(self, _scope: Any, entity: Any) -> Any:
        return entity


class FakeBackend:
    def __init__(self) -> None:
        self.uploaded: list[dict[str, Any]] = []

    async def merge_or_upload_documents(self, documents: list[dict[str, Any]], **_: Any) -> Any:
        self.uploaded.extend(documents)
        return [SimpleNamespace(succeeded=True) for _ in documents]

    async def delete_documents(self, documents: list[dict[str, Any]], **_: Any) -> Any:
        return [SimpleNamespace(succeeded=True) for _ in documents]


def _wrap(settings: WorkerSearchSettings, backend: FakeBackend | None) -> tuple[Any, Any]:
    repo = StubRepo()
    wrapped = wrap_catalog_for_search(
        "commercial",
        cast(Any, SimpleNamespace()),
        ClientLifetime(),
        cast(Any, repo),
        backend=backend,
        settings=settings,
    )
    return repo, wrapped


async def test_azure_provider_writes_a_projection_through_to_the_index() -> None:
    backend = FakeBackend()
    settings = WorkerSearchSettings(provider="azure", region="eastus", service="svc")
    _repo, wrapped = _wrap(settings, backend)
    assert isinstance(wrapped, IndexingCatalogRepository)
    entity = {"id": ENTITY_ID, "domain_id": f"commercial:{NS}:dom:a", "name": "first"}
    await wrapped.create_entity(SCOPE, cast(Any, entity))
    assert len(backend.uploaded) == 1
    assert backend.uploaded[0]["entity_id"] == ENTITY_ID


@pytest.mark.parametrize(
    "settings",
    [
        WorkerSearchSettings(),
        WorkerSearchSettings(provider="fixture", region="eastus", service="svc"),
        WorkerSearchSettings(provider="azure", service="svc"),  # no region
        WorkerSearchSettings(provider="azure", region="eastus"),  # no service
    ],
)
async def test_nothing_is_wrapped_otherwise(settings: WorkerSearchSettings) -> None:
    repo, wrapped = _wrap(settings, None)
    assert wrapped is repo


async def test_unsupported_region_is_not_wrapped_and_makes_no_request() -> None:
    backend = FakeBackend()
    settings = WorkerSearchSettings(provider="azure", region="nowhere-land", service="svc")
    repo, wrapped = _wrap(settings, backend)
    assert wrapped is repo
    assert backend.uploaded == []
