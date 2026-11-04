"""Catalog indexer: scoped enumeration, idempotent upserts, Azure sink, no bodies logged."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from catalog.graph_helpers import (  # pyright: ignore[reportMissingImports]
    NS,
    agent,
    budget,
    dom,
    make_scope,
)
from neurosphere_core.catalog import GraphSearchRequest
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.search.fixture.index import SearchDocument
from neurosphere_core.search.indexer import (
    AzureIndexSink,
    CatalogIndexer,
    CompositeIndexSink,
    FixtureSearchStore,
)

SCOPE_A = make_scope(NS, [dom(NS, "a")])
SCOPE_B = make_scope(NS, [dom(NS, "b")])
SCOPE_AB = make_scope(NS, [dom(NS, "a"), dom(NS, "b")])
RESTRICTED_TEXT = "classified-payroll-bot"


class RecordingSink:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        self.batches.append([d.id for d in documents])


class FakeUploadBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self._fail = fail

    async def merge_or_upload_documents(
        self, documents: list[dict[str, Any]], **_kwargs: Any
    ) -> Any:
        self.calls.append(documents)
        return [SimpleNamespace(succeeded=not self._fail) for _ in documents]


async def _seeded() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await repo.create_entity(SCOPE_A, agent(NS, "alpha1", "a"))
    await repo.create_entity(SCOPE_A, agent(NS, "alpha2", "a"))
    await repo.create_entity(
        SCOPE_B, agent(NS, "restricted", "b", display_name=f"Agent {RESTRICTED_TEXT}")
    )
    return repo


async def test_refresh_indexes_only_what_the_scope_can_read() -> None:
    repo = await _seeded()
    sink = RecordingSink()
    sent = await CatalogIndexer(repo, sink).refresh(SCOPE_A)
    assert sent == 2
    assert all(":agent:restricted" not in i for batch in sink.batches for i in batch)


async def test_refresh_is_idempotent() -> None:
    repo = await _seeded()
    sink = RecordingSink()
    indexer = CatalogIndexer(repo, sink)
    assert await indexer.refresh(SCOPE_AB) == 3
    assert await indexer.refresh(SCOPE_AB) == 0
    assert len(sink.batches) == 1
    # a changed entity is sent again, an unchanged one is not
    stored = await repo.get_entity(SCOPE_A, f"commercial:{NS}:foundry:agent:alpha1")
    assert stored is not None
    changed = agent(NS, "alpha1", "a", display_name="Agent renamed")
    await repo.update_entity(SCOPE_A, changed, stored.etag.root)  # type: ignore[arg-type]
    assert await indexer.refresh(SCOPE_AB) == 1


async def test_failed_sink_is_retried_not_remembered() -> None:
    repo = await _seeded()
    backend = FakeUploadBackend(fail=True)
    indexer = CatalogIndexer(repo, AzureIndexSink(backend))
    with pytest.raises(DependencyTransientError):
        await indexer.refresh(SCOPE_A)
    backend._fail = False  # pyright: ignore[reportPrivateUsage]
    assert await indexer.refresh(SCOPE_A) == 2


async def test_fixture_search_returns_matches_and_hides_restricted_entities() -> None:
    repo = await _seeded()
    store = FixtureSearchStore()
    indexer = CatalogIndexer(repo, store)
    # an indexer that ran for a wider principal must not leak to a narrower one
    await indexer.refresh(SCOPE_AB)
    query = RepositoryGraphQuery(repo, store)
    request = GraphSearchRequest(term=RESTRICTED_TEXT.split("-")[0], budget=budget())

    visible = await query.search(SCOPE_B, request)
    assert [n.id for n in visible.nodes] == [f"commercial:{NS}:foundry:agent:restricted"]

    hidden = await query.search(SCOPE_A, request)
    assert hidden.nodes == []

    own = await query.search(SCOPE_A, GraphSearchRequest(term="agent", budget=budget()))
    assert {n.id for n in own.nodes} == {
        f"commercial:{NS}:foundry:agent:alpha1",
        f"commercial:{NS}:foundry:agent:alpha2",
    }


async def test_azure_sink_upserts_documents_without_a_key_path() -> None:
    repo = await _seeded()
    backend = FakeUploadBackend()
    store = FixtureSearchStore()
    sink = CompositeIndexSink(store, AzureIndexSink(backend))
    assert await CatalogIndexer(repo, sink).refresh(SCOPE_A) == 2
    assert len(backend.calls) == 1
    for doc in backend.calls[0]:
        assert set(doc) == {"id", "entity", "cloud", "customer_id", "domain_id", "text"}
    assert len(store) == 2


async def test_document_bodies_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    repo = await _seeded()
    caplog.set_level(logging.DEBUG)
    await CatalogIndexer(repo, RecordingSink()).refresh(SCOPE_AB)
    with pytest.raises(DependencyTransientError):
        await CatalogIndexer(repo, AzureIndexSink(FakeUploadBackend(fail=True))).refresh(SCOPE_AB)
    assert RESTRICTED_TEXT not in caplog.text
    assert "alpha1" not in caplog.text
