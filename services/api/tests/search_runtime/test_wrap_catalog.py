"""``wrap_catalog_for_search``: wraps only when a provider is configured; writes are searchable."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from neurosphere_api.runtime.builders import search as search_module
from neurosphere_api.runtime.builders.search import SearchRuntime, wrap_catalog_for_search
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.search.indexer import CatalogIndexer, FixtureSearchStore
from neurosphere_core.search.write_hook import IndexingCatalogRepository
from runtime_data.test_search_builder import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    _agent,  # pyright: ignore[reportPrivateUsage]
    _compose,  # pyright: ignore[reportPrivateUsage]
    _ids,  # pyright: ignore[reportPrivateUsage]
    _seeder,  # pyright: ignore[reportPrivateUsage]
)


def _ctx(runtime: object | None) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(search_runtime=runtime)))


def test_no_provider_returns_the_repository_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "build_catalog_graph", lambda _ctx, _repo: None)
    repo = InMemoryCatalogRepository()
    wrapped, graph = wrap_catalog_for_search(_ctx(None), repo)
    assert wrapped is repo and graph is None


def test_provider_wraps_and_invalidates_on_write(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryCatalogRepository()
    invalidated: list[int] = []
    runtime = SearchRuntime(
        provider="fixture",
        azure_enabled=False,
        disabled_reason=None,
        indexer=CatalogIndexer(repo, FixtureSearchStore()),
        _invalidate=lambda: invalidated.append(1),
    )
    sentinel = object()
    monkeypatch.setattr(search_module, "build_catalog_graph", lambda _ctx, _repo: sentinel)
    wrapped, graph = wrap_catalog_for_search(_ctx(runtime), repo)
    assert graph is sentinel
    assert isinstance(wrapped, IndexingCatalogRepository)
    asyncio.run(wrapped.create_entity(_seeder([FINANCE]), _agent("w1", FINANCE, "payroll")))
    assert invalidated == [1]


def test_write_through_makes_a_write_searchable_without_waiting_for_the_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, _repo = _compose(
        monkeypatch, {"NS_SEARCH_PROVIDER": "fixture", "NS_SEARCH_REFRESH_SECONDS": "3600"}
    )
    first = _ids(composed)
    wrapped = composed.app.state.catalog_repository  # the data builder published the wrapper
    assert isinstance(wrapped, IndexingCatalogRepository)
    asyncio.run(
        wrapped.create_entity(
            _seeder([FINANCE]), _agent("payroll-three", FINANCE, "payroll third finance agent")
        )
    )
    # the write went to the sink directly; the refresh window (3600 s) has not elapsed
    assert f"commercial:{CUSTOMER}:foundry:agent:payroll-three" not in first
    assert len(_ids(composed)) == len(first) + 1
