"""Layout: {customer}/{domain or _none}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz by UTC event day."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_workers.archive import blob_name, partition_prefix

from .support import T0, Doc, FakeContainer, make_event, make_sink, read_blob


async def test_day_and_domain_partition(template: Doc, container: FakeContainer) -> None:
    event = await make_event(template, "evt-p1", T0, domain_id="dom-a")
    await make_sink(container).write(event)

    cust = event.message.customer_id
    assert list(container.blobs) == [f"{cust}/dom-a/2026/10/01/{event.doc_id}.json.gz"]
    assert read_blob(container.blobs[blob_name(event)])["doc_id"] == event.doc_id


async def test_missing_domain_goes_to_none(template: Doc, container: FakeContainer) -> None:
    event = await make_event(template, "evt-p2", T0, domain_id=None)
    await make_sink(container).write(event)
    (name,) = container.blobs
    assert name.split("/")[1] == "_none"


async def test_distinct_domains_and_days_are_distinct_partitions(
    template: Doc, container: FakeContainer
) -> None:
    sink = make_sink(container)
    for i, (dom, moment) in enumerate(
        [("dom-a", T0), ("dom-b", T0), ("dom-a", T0 + timedelta(days=1))]
    ):
        await sink.write(await make_event(template, f"evt-p3-{i}", moment, domain_id=dom))
    prefixes = {n.rsplit("/", 1)[0] for n in container.blobs}
    assert len(prefixes) == 3


async def test_utc_day_boundary(template: Doc, container: FakeContainer) -> None:
    sink = make_sink(container)
    last = datetime(2026, 10, 1, 23, 59, 59, 999000, tzinfo=UTC)
    first = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)
    await sink.write(await make_event(template, "evt-b1", last))
    await sink.write(await make_event(template, "evt-b2", first))
    days = sorted(n.split("/")[4] for n in container.blobs)
    assert days == ["01", "02"]


async def test_day_is_utc_not_local(template: Doc, container: FakeContainer) -> None:
    # 2026-10-01T23:30-05:00 is 2026-10-02T04:30Z.
    local = datetime(2026, 10, 1, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    event = await make_event(template, "evt-b3", local)
    await make_sink(container).write(event)
    (name,) = container.blobs
    assert name.split("/")[2:5] == ["2026", "10", "02"]


@pytest.mark.parametrize("bad", ["", "a/b", "..", "a\\b", "x\ny", "_none"])
def test_unsafe_domain_segments_are_refused(bad: str) -> None:
    with pytest.raises(InvalidSchemaError):
        partition_prefix("cust", bad, date(2026, 10, 1))


def test_unsafe_customer_segment_is_refused() -> None:
    with pytest.raises(InvalidSchemaError):
        partition_prefix("../other", None, date(2026, 10, 1))
