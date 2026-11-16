"""Indexer deletes: removal by absence, ref counting across scopes, retry, Azure delete sink."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest
from catalog.graph_helpers import NS, dom, make_scope  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.paging import Page
from neurosphere_core.search.azure.schema import decode_document_key
from neurosphere_core.search.fixture.index import SearchDocument
from neurosphere_core.search.indexer import (
    AzureIndexSink,
    CatalogIndexer,
    CompositeIndexSink,
    FixtureSearchStore,
)

SCOPE_A = make_scope(NS, [dom(NS, "a")])
SCOPE_B = make_scope(NS, [dom(NS, "b")])
DOMAIN_A = dom(NS, "a")


def _ent(local: str) -> dict[str, Any]:
    return {"id": f"commercial:{NS}:foundry:agent:{local}", "domain_id": DOMAIN_A, "name": local}


def _id(local: str) -> str:
    return f"commercial:{NS}:foundry:agent:{local}"


class StubRepo:
    """Returns a configurable entity list per scope domain, one page."""

    def __init__(self) -> None:
        self.by_domain: dict[str, list[dict[str, Any]]] = {}
        self.truncate = False

    async def list_entities(self, scope: Any, _flt: Any, _page: Any) -> Any:
        items: list[dict[str, Any]] = []
        for d in sorted(scope.allowed_domains):
            items.extend(self.by_domain.get(str(d), []))
        if self.truncate:
            return SimpleNamespace(items=items, next_cursor="more")
        return Page(items=tuple(items))


class RecordingSink:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.upserts: list[list[str]] = []
        self.deletes: list[list[str]] = []
        self.fail_delete = fail_delete

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        self.upserts.append([d.id for d in documents])

    async def delete(self, ids: Sequence[str]) -> None:
        if self.fail_delete:
            raise DependencyTransientError("boom", reason="search_index_delete_failed")
        self.deletes.append(list(ids))


def _indexer(repo: StubRepo, sink: Any) -> CatalogIndexer:
    return CatalogIndexer(cast(CatalogRepository, repo), sink)


async def test_entity_leaving_the_enumeration_is_deleted() -> None:
    repo, sink = StubRepo(), RecordingSink()
    repo.by_domain[DOMAIN_A] = [_ent("one"), _ent("two")]
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    assert sink.deletes == []
    repo.by_domain[DOMAIN_A] = [_ent("one")]
    await indexer.refresh(SCOPE_A)
    assert sink.deletes == [[_id("two")]]
    # re-adding re-upserts (the digest was dropped after the delete was accepted)
    repo.by_domain[DOMAIN_A] = [_ent("one"), _ent("two")]
    assert await indexer.refresh(SCOPE_A) == 1


async def test_document_held_by_another_scope_is_not_deleted_by_a_stale_scope() -> None:
    repo, sink = StubRepo(), RecordingSink()
    shared = _ent("shared")
    repo.by_domain[DOMAIN_A] = [shared]
    both = make_scope(NS, [DOMAIN_A, dom(NS, "b")])
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    await indexer.refresh(both)  # both scopes now hold "shared"
    repo.by_domain[DOMAIN_A] = []
    await indexer.refresh(SCOPE_A)  # A no longer sees it, but `both` last did
    assert sink.deletes == []
    await indexer.refresh(both)  # now nobody holds it
    assert sink.deletes == [[_id("shared")]]


async def test_truncated_enumeration_never_deletes() -> None:
    repo, sink = StubRepo(), RecordingSink()
    repo.by_domain[DOMAIN_A] = [_ent("one")]
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    repo.by_domain[DOMAIN_A] = []
    repo.truncate = True
    await indexer.refresh(SCOPE_A)
    assert sink.deletes == []


async def test_failed_delete_raises_and_is_retried() -> None:
    repo, sink = StubRepo(), RecordingSink(fail_delete=True)
    repo.by_domain[DOMAIN_A] = [_ent("one")]
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    repo.by_domain[DOMAIN_A] = []
    with pytest.raises(DependencyTransientError):
        await indexer.refresh(SCOPE_A)
    sink.fail_delete = False
    await indexer.refresh(SCOPE_A)  # nothing changed in the enumeration; the retry still happens
    assert sink.deletes == [[_id("one")]]


async def test_explicit_remove_and_fixture_store() -> None:
    repo = StubRepo()
    repo.by_domain[DOMAIN_A] = [_ent("one"), _ent("two")]
    store = FixtureSearchStore()
    indexer = _indexer(repo, store)
    await indexer.refresh(SCOPE_A)
    assert len(store) == 2
    assert await indexer.remove([_id("one")]) == 1
    assert len(store) == 1
    await store.delete(["not-there"])
    assert len(store) == 1
    assert await indexer.remove([]) == 0


async def test_composite_and_azure_delete_use_encoded_keys() -> None:
    calls: list[list[dict[str, Any]]] = []

    class Backend:
        def __init__(self, ok: bool) -> None:
            self.ok = ok

        async def merge_or_upload_documents(self, documents: list[dict[str, Any]], **_k: Any):
            return [SimpleNamespace(succeeded=True) for _ in documents]

        async def delete_documents(self, documents: list[dict[str, Any]], **_k: Any):
            calls.append(documents)
            return [SimpleNamespace(succeeded=self.ok) for _ in documents]

    store = FixtureSearchStore()
    await CompositeIndexSink(store, AzureIndexSink(Backend(True))).delete([_id("x")])
    assert [decode_document_key(d["id"]) for d in calls[0]] == [_id("x")]
    with pytest.raises(DependencyTransientError) as err:
        await AzureIndexSink(Backend(False)).delete([_id("x")])
    assert err.value.reason == "search_index_delete_failed"


async def test_delete_logs_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    repo, sink = StubRepo(), RecordingSink()
    repo.by_domain[DOMAIN_A] = [_ent("secretname")]
    caplog.set_level(logging.DEBUG)
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    repo.by_domain[DOMAIN_A] = []
    await indexer.refresh(SCOPE_A)
    assert "secretname" not in caplog.text


async def test_digest_is_dropped_before_the_delete_await_so_a_concurrent_scope_reupserts() -> None:
    repo = StubRepo()
    repo.by_domain[DOMAIN_A] = [_ent("one")]
    seen_during_delete: list[bool] = []

    class _Sink(RecordingSink):
        async def delete(self, ids: Sequence[str]) -> None:
            seen_during_delete.append(_id("one") in indexer._seen)  # pyright: ignore[reportPrivateUsage]
            await super().delete(ids)

    sink = _Sink()
    indexer = _indexer(repo, sink)
    await indexer.refresh(SCOPE_A)
    repo.by_domain[DOMAIN_A] = []
    await indexer.refresh(SCOPE_A)
    assert seen_during_delete == [False]
