"""build_manifest: lists a partition-day, idempotent, safe to re-run."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from .support import T0, Doc, FakeContainer, make_event, make_sink

NOW = datetime(2026, 10, 3, 1, 0, tzinfo=UTC)


async def test_manifest_lists_the_partition_day(template: Doc, container: FakeContainer) -> None:
    sink = make_sink(container, clock=lambda: NOW)
    events = [await make_event(template, f"evt-m{i}", T0) for i in range(3)]
    other_day = await make_event(template, "evt-m-other", T0 + timedelta(days=1))
    other_dom = await make_event(template, "evt-m-dom", T0, domain_id="dom-b")
    for event in [*events, other_day, other_dom]:
        await sink.write(event)

    cust = events[0].message.customer_id
    manifest = await sink.build_manifest(cust, "dom-a", date(2026, 10, 1))

    assert manifest.count == 3
    assert [e.doc_id for e in manifest.entries] == sorted(e.doc_id for e in events)
    assert all(e.sha256 for e in manifest.entries)
    assert manifest.generated_at == "2026-10-03T01:00:00Z"
    stored = json.loads(container.blobs[f"{cust}/dom-a/2026/10/01/manifest.json"])
    assert stored["count"] == 3
    assert stored["entries"][0]["sha256"] == manifest.entries[0].sha256


async def test_manifest_is_idempotent_and_ignores_itself(
    template: Doc, container: FakeContainer
) -> None:
    sink = make_sink(container, clock=lambda: NOW)
    event = await make_event(template, "evt-m-idem", T0)
    await sink.write(event)
    cust = event.message.customer_id

    first = await sink.build_manifest(cust, "dom-a", date(2026, 10, 1))
    snapshot = dict(container.blobs)
    second = await sink.build_manifest(cust, "dom-a", date(2026, 10, 1))

    assert first == second
    assert container.blobs == snapshot
    assert second.count == 1


async def test_manifest_picks_up_late_arrivals_on_rerun(
    template: Doc, container: FakeContainer
) -> None:
    sink = make_sink(container, clock=lambda: NOW)
    a = await make_event(template, "evt-m-a", T0)
    await sink.write(a)
    cust = a.message.customer_id
    assert (await sink.build_manifest(cust, "dom-a", date(2026, 10, 1))).count == 1

    await sink.write(await make_event(template, "evt-m-b", T0))
    assert (await sink.build_manifest(cust, "dom-a", date(2026, 10, 1))).count == 2


async def test_empty_partition_and_none_domain(template: Doc, container: FakeContainer) -> None:
    sink = make_sink(container, clock=lambda: NOW)
    empty = await sink.build_manifest("cust-x", None, date(2026, 10, 1))
    assert empty.count == 0
    assert "cust-x/_none/2026/10/01/manifest.json" in container.blobs
