"""Cross-customer, cross-cloud, out-of-scope-domain and malformed blobs never reach a series."""

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

AGENT = "commercial:synthco:sandbox:agent:a-1"
WINDOW = (date(2026, 10, 1), date(2026, 10, 2))
AGENT_DOC = {
    "id": AGENT,
    "cloud": CLOUD,
    "customer_id": CUSTOMER,
    "domain_id": DOMAIN,
    "lifecycle_status": "active",
}


def _load(container: FakeContainer) -> ArchiveSeriesSource:
    return asyncio.run(
        ArchiveSeriesSource.load(
            ArchiveReader(container),
            scope=make_scope(),
            agents=[AGENT_DOC],
            owners={},
            window=WINDOW,
        )
    )


def _events(source: ArchiveSeriesSource) -> int | None:
    (series,) = source.series(
        cloud=CLOUD,
        customer_id=CUSTOMER,
        domain_ids=frozenset({DOMAIN}),
        start=WINDOW[0],
        end=WINDOW[1],
    )
    return series.days[0].event_count


def test_in_scope_blob_is_counted() -> None:
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    assert _events(_load(container)) == 1


def test_other_customer_is_never_read() -> None:
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    put_contract(container, "telemetry", telemetry_doc(2, customer="othercorp"), "d2")
    source = _load(container)
    assert _events(source) == 1
    assert all(not name.startswith("othercorp/") for name in container.downloads)


def test_blob_lying_about_its_customer_is_dropped() -> None:
    """A blob under our prefix whose decoded message belongs to another customer is not used."""
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    name = put_contract(container, "telemetry", telemetry_doc(2, customer="othercorp"), "d2")
    container.blobs[f"synthco/{name.split('/', 1)[1]}"] = container.blobs.pop(name)
    source = _load(container)
    assert _events(source) == 1
    assert source.archive_stats.unreadable == 1


def test_other_cloud_inside_our_prefix_is_dropped() -> None:
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    put_contract(container, "telemetry", telemetry_doc(2, cloud="government"), "d2")
    source = _load(container)
    assert _events(source) == 1
    assert source.archive_stats.out_of_scope == 1


def test_domain_outside_scope_is_not_downloaded() -> None:
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    other = "commercial:synthco:sandbox:domain:dom-999"
    name = put_contract(container, "telemetry", telemetry_doc(2, domain=other), "d2")
    source = _load(container)
    assert _events(source) == 1
    assert name not in container.downloads
    assert source.archive_stats.out_of_scope == 1


def test_malformed_blobs_are_skipped_and_counted() -> None:
    container = FakeContainer()
    put_contract(container, "telemetry", telemetry_doc(1), "d1")
    container.put_raw(
        "synthco/commercial:synthco:sandbox:domain:dom-001/2026/10/01/bad.json.gz", b"nope"
    )
    bad = telemetry_doc(3)
    del bad["event_id"]
    put_contract(container, "telemetry", bad, "d3")
    source = _load(container)
    assert _events(source) == 1
    assert source.archive_stats.unreadable == 1
    assert source.stats.telemetry_skipped == 1
