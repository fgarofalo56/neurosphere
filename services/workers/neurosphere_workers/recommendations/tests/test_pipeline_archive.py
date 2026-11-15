"""Archive-mode pipeline: live catalog (read-only) plus archive blobs, over in-memory fakes.

The same synthetic sandbox documents are served once as files (sandbox run) and once as archive
blobs (archive run); both must store the same records. No network, no Cosmos, no compose.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as SearchScope
from neurosphere_core.catalog.graph.query import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import EntityFilter
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import SearchRequest, SearchResult

from neurosphere_workers.recommendations.pipeline import (
    PipelineSummary,
    load_sandbox_catalog,
    run_pipeline,
    run_pipeline_archive,
)
from neurosphere_workers.recommendations.rules.tests.archive_support import (
    FakeContainer,
    archive_from_sandbox,
)
from neurosphere_workers.recommendations.tests.support import (
    PAIRS,
    generate_sandbox,
    make_scope,
    synthetic_prices,
)
from neurosphere_workers.runtime.archive_reader import ArchiveReader

# Sandbox days are 2026-10-01 to 2026-10-07; a run on the 8th with 7 days of lookback sees them.
RUN_AT = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


class ReadOnlyLister:
    """The one read the pipeline needs; any other repository method is an AttributeError."""

    def __init__(self, repo: Any) -> None:
        self._repo = repo
        self.calls = 0

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[Any]:
        self.calls += 1
        return await self._repo.list_entities(scope, flt, page)


@pytest.fixture(scope="module")
def sandbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pipeline-archive-sandbox")
    generate_sandbox(out, seed=3)
    return out


@pytest.fixture(scope="module")
def container(sandbox_dir: Path) -> FakeContainer:
    fake = FakeContainer()
    archive_from_sandbox(sandbox_dir, fake)
    return fake


def _scope(directory: Path) -> IdentityScope:
    import json

    lines = (directory / "domains.ndjson").read_text(encoding="utf-8").splitlines()
    return make_scope(sorted(json.loads(line)["id"] for line in lines if line))


async def _archive_run(
    directory: Path, container: FakeContainer, *, max_blobs: int = 500_000, **kw: Any
) -> tuple[PipelineSummary, InMemoryRecommendationStore, ReadOnlyLister]:
    scope = _scope(directory)
    graph, repo = await load_sandbox_catalog(directory, scope=scope)
    lister = ReadOnlyLister(repo)
    store = InMemoryRecommendationStore()
    summary = await run_pipeline_archive(
        ArchiveReader(container, max_blobs=max_blobs),
        graph=graph,
        lister=lister,
        scope=scope,
        store=store,
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=RUN_AT,
        lookback_days=7,
        **kw,
    )
    return summary, store, lister


async def test_archive_run_stores_the_same_records_as_the_sandbox_run(
    sandbox_dir: Path, container: FakeContainer
) -> None:
    sandbox_store = InMemoryRecommendationStore()
    expected = await run_pipeline(
        sandbox_dir,
        scope=_scope(sandbox_dir),
        store=sandbox_store,
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=RUN_AT,
    )
    actual, _store, lister = await _archive_run(sandbox_dir, container)
    assert expected.stored > 0
    assert actual.counts_by_kind == expected.counts_by_kind
    assert sorted(actual.stored_ids) == sorted(expected.stored_ids)
    assert actual.window == expected.window
    assert actual.archive_truncated is False
    assert lister.calls > 0


async def test_truncated_archive_reports_it_and_never_emits_unused_agent(
    sandbox_dir: Path, container: FakeContainer
) -> None:
    summary, _store, _lister = await _archive_run(sandbox_dir, container, max_blobs=100)
    assert summary.archive_truncated is True
    assert summary.counts_by_kind.get("unused_agent", 0) == 0
    assert summary.rule_outcomes.get("unknown_coverage", 0) > 0


async def test_empty_archive_is_unknown_not_unused(sandbox_dir: Path) -> None:
    summary, _store, _lister = await _archive_run(sandbox_dir, FakeContainer())
    assert summary.counts_by_kind.get("unused_agent", 0) == 0
    assert summary.usage_summaries == 0


class CountingSearch:
    """Stands in for the search index; ``run_pipeline_archive`` must never call it."""

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, scope: SearchScope, request: SearchRequest) -> SearchResult:
        self.calls += 1
        raise AssertionError("the archive pipeline must not search")


async def test_duplicate_detection_never_searches(
    sandbox_dir: Path, container: FakeContainer
) -> None:
    # PRP-15 reviewer follow-up: ``run_pipeline_archive`` hands the repository over as graph and
    # lister (production wiring builds the graph over an empty index). Duplicate candidates come
    # from catalog reads only; this pins that, so a future detector change that searches fails here.
    scope = _scope(sandbox_dir)
    _graph, repo = await load_sandbox_catalog(sandbox_dir, scope=scope)
    search = CountingSearch()
    summary = await run_pipeline_archive(
        ArchiveReader(container),
        graph=RepositoryGraphQuery(repo, search),
        lister=ReadOnlyLister(repo),
        scope=scope,
        store=InMemoryRecommendationStore(),
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=RUN_AT,
        lookback_days=7,
    )
    assert summary.stored > 0
    assert search.calls == 0
