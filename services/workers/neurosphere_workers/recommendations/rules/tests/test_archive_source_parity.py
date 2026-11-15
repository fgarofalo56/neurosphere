"""The archive source gives the same series as the sandbox source over the same documents."""

from __future__ import annotations

import asyncio

from neurosphere_workers.recommendations.rules import ArchiveSeriesSource
from neurosphere_workers.recommendations.rules.tests.archive_support import (
    FakeContainer,
    agent_docs,
    archive_from_sandbox,
    owner_map,
)
from neurosphere_workers.recommendations.rules.tests.conftest import SandboxRun
from neurosphere_workers.recommendations.rules.tests.support import make_scope
from neurosphere_workers.runtime.archive_reader import ArchiveReader


def test_archive_series_equal_sandbox_series(sandbox_run: SandboxRun) -> None:
    container = FakeContainer()
    archive_from_sandbox(sandbox_run.directory, container)
    window = sandbox_run.source.observed_window()
    assert window is not None
    scope = make_scope(tuple(sandbox_run.domains))
    loaded = asyncio.run(
        ArchiveSeriesSource.load(
            ArchiveReader(container, max_blobs=500_000),
            scope=scope,
            agents=agent_docs(sandbox_run.directory),
            owners=owner_map(sandbox_run.directory),
            window=window,
        )
    )
    kwargs = {
        "cloud": "commercial",
        "customer_id": "synthco",
        "domain_ids": frozenset(sandbox_run.domains),
        "start": window[0],
        "end": window[1],
    }
    expected = list(sandbox_run.source.series(**kwargs))
    actual = list(loaded.series(**kwargs))
    assert expected
    assert actual == expected
    assert loaded.truncated is False
    assert loaded.observed_window() == window
