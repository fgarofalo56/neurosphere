"""Write-through wrapper: indexed on create/update/deprecate, failures never fail the write."""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest
from catalog.graph_helpers import NS, agent, dom, make_scope  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog import CatalogRepository
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_core.search.fixture.index import SearchDocument
from neurosphere_core.search.indexer import CatalogIndexer
from neurosphere_core.search.write_hook import IndexingCatalogRepository

SCOPE = make_scope(NS, [dom(NS, "a")])


class Sink:
    def __init__(self, *, fail: bool = False) -> None:
        self.docs: dict[str, SearchDocument] = {}
        self.fail = fail

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        if self.fail:
            raise DependencyTransientError("down", reason="search_index_upload_failed")
        for d in documents:
            self.docs[d.id] = d

    async def delete(self, ids: Sequence[str]) -> None:
        for i in ids:
            self.docs.pop(i, None)


def _wrap(sink: Sink, writes: list[int] | None = None) -> IndexingCatalogRepository:
    inner = InMemoryCatalogRepository()
    indexer = CatalogIndexer(inner, sink)
    on_write = (lambda: writes.append(1)) if writes is not None else None
    return IndexingCatalogRepository(inner, indexer, on_write=on_write)


async def test_wrapper_satisfies_the_repository_protocol() -> None:
    assert isinstance(_wrap(Sink()), CatalogRepository)


async def test_create_update_deprecate_are_written_through() -> None:
    sink, writes = Sink(), []
    repo = _wrap(sink, writes)
    created = await repo.create_entity(SCOPE, agent(NS, "one", "a", display_name="first text"))
    doc_id = f"commercial:{NS}:foundry:agent:one"
    assert sink.docs[doc_id].text.startswith("first text") or "first text" in sink.docs[doc_id].text

    changed = agent(NS, "one", "a", display_name="second text")
    updated = await repo.update_entity(SCOPE, changed, created.etag.root)
    assert "second text" in sink.docs[doc_id].text

    await repo.deprecate_entity(SCOPE, doc_id, updated.etag.root)
    assert doc_id in sink.docs  # deprecation stays whatever list_entities decides (PRP-60 #5)
    assert len(writes) == 3
    # reads are forwarded
    assert (await repo.get_entity(SCOPE, doc_id)) is not None


async def test_sink_failure_does_not_fail_the_write_and_logs_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    repo = _wrap(Sink(fail=True))
    created = await repo.create_entity(SCOPE, agent(NS, "secretbot", "a"))
    assert created is not None
    assert "DependencyTransientError" in caplog.text
    assert "secretbot" not in caplog.text


async def test_failed_inner_write_is_not_indexed() -> None:
    sink = Sink()
    repo = _wrap(sink)
    with pytest.raises(InvalidSchemaError):
        await repo.update_entity(SCOPE, agent(NS, "ghost", "a"), "etag")
    assert sink.docs == {}
