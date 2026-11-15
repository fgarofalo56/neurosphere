"""Unknown is not zero: uncovered days and truncated listings never read as unused."""

from __future__ import annotations

import asyncio
from datetime import date

from neurosphere_workers.recommendations.rules import ArchiveSeriesSource
from neurosphere_workers.recommendations.rules.tests.archive_docs import telemetry_doc
from neurosphere_workers.recommendations.rules.tests.archive_support import (
    FakeContainer,
    put_contract,
)
from neurosphere_workers.recommendations.rules.tests.support import (
    CLOUD,
    CUSTOMER,
    DOMAIN,
    make_scope,
)
from neurosphere_workers.runtime.archive_reader import ArchiveReader

WINDOW = (date(2026, 10, 1), date(2026, 10, 4))
AGENTS = [
    {
        "id": f"commercial:synthco:sandbox:agent:a-{i}",
        "cloud": CLOUD,
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "lifecycle_status": "active",
    }
    for i in (1, 2)
]


def _load(
    container: FakeContainer, *, max_blobs: int = 20_000, max_docs: int = 100_000
) -> ArchiveSeriesSource:
    return asyncio.run(
        ArchiveSeriesSource.load(
            ArchiveReader(container, max_blobs=max_blobs),
            scope=make_scope(),
            agents=AGENTS,
            owners={},
            window=WINDOW,
            max_docs=max_docs,
        )
    )


def _series(source: ArchiveSeriesSource) -> dict[str, tuple[tuple[bool, int | None], ...]]:
    return {
        s.agent_id: tuple((d.covered, d.event_count) for d in s.days)
        for s in source.series(
            cloud=CLOUD,
            customer_id=CUSTOMER,
            domain_ids=frozenset({DOMAIN}),
            start=WINDOW[0],
            end=WINDOW[1],
        )
    }


def test_uncovered_day_is_unknown_and_idle_agent_on_covered_day_is_zero() -> None:
    container = FakeContainer()
    # Days 1 and 3 have events from agent 1 only; day 2 has nothing from anyone.
    put_contract(container, "telemetry", telemetry_doc(1, day="2026-10-01"), "d1")
    put_contract(container, "telemetry", telemetry_doc(2, day="2026-10-03"), "d2")
    got = _series(_load(container))
    assert got["commercial:synthco:sandbox:agent:a-1"] == ((True, 1), (False, None), (True, 1))
    assert got["commercial:synthco:sandbox:agent:a-2"] == ((True, 0), (False, None), (True, 0))


def test_truncated_listing_marks_everything_unknown() -> None:
    container = FakeContainer()
    for n in range(5):
        put_contract(container, "telemetry", telemetry_doc(n, day="2026-10-01"), f"d{n}")
    source = _load(container, max_blobs=3)
    assert source.truncated is True
    assert all(
        covered is False and count is None
        for days in _series(source).values()
        for covered, count in days
    )


def test_per_run_document_bound_marks_truncated() -> None:
    container = FakeContainer()
    for n in range(4):
        put_contract(container, "telemetry", telemetry_doc(n, day="2026-10-01"), f"d{n}")
    source = _load(container, max_docs=2)
    assert source.truncated is True
    assert len(container.downloads) == 2
