"""BillingExportPoller: export -> invoiced CostRecord CloudEvents, checkpoint, failure handling."""

from __future__ import annotations

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_core.payload import CLOUDEVENT_TYPE_COST
from neurosphere_workers.ingestion.billing_export import (
    STATUS_INCOMPLETE,
    STATUS_INGEST_FAILED,
    STATUS_OK,
    STATUS_READ_FAILED,
    STATUS_UNCHANGED,
)

from .support import (
    CSV0,
    DOMAIN,
    PART0,
    PART1,
    SOURCE,
    FakeBlobSource,
    FakeIngest,
    default_source,
    make_poller,
    manifest,
)


def _records(ingest: FakeIngest) -> list[CostRecord]:
    return [CostRecord.model_validate(e["data"]) for e in ingest.events]


async def test_export_becomes_invoiced_billing_cost_records() -> None:
    ingest = FakeIngest()
    poller = make_poller(default_source(), ingest)
    await poller.tick()

    assert poller.last_status.status == STATUS_OK
    assert {e["type"] for e in ingest.events} == {CLOUDEVENT_TYPE_COST}
    records = _records(ingest)
    # day/resource/meter groups: (10/R1/m-in)=2.00, (10/R2/m-sku)=3.10, (11/R1/m-in)=4.00;
    # (11/R2/m-sku) has a blank cost: unknown, skipped, never 0.
    assert sorted(r.amount.root for r in records) == ["2.00", "3.10", "4.00"]
    assert poller.last_status.skipped_null_cost == 1
    for r in records:
        assert r.kind == "invoiced"
        assert r.observation_source == "billing"
        assert r.currency == "USD"
        assert r.domain_id is not None and r.domain_id.root == DOMAIN
        assert r.source_id.root == SOURCE
        assert r.billing_period is not None
        assert r.billing_period.start_date == r.billing_period.end_date  # export granularity: a day
        day = r.billing_period.start_date.root
        assert r.usage_start is not None and r.usage_start.root == f"{day}T00:00:00Z"
        assert r.usage_end is not None and r.usage_end.root == f"{day}T23:59:59Z"
        assert r.dedupe_key.root.startswith("azure-billing:")
    # The CloudEvent id is the cost id (the pipeline dedupes on it).
    assert [e["id"] for e in ingest.events] == [r.cost_id.root for r in records]


async def test_second_tick_of_the_same_export_does_not_repost() -> None:
    ingest = FakeIngest()
    poller = make_poller(default_source(), ingest)
    await poller.tick()
    first = len(ingest.events)
    await poller.tick()
    assert poller.last_status.status == STATUS_UNCHANGED
    assert len(ingest.events) == first


async def test_rewritten_export_reposts_with_the_same_ids() -> None:
    ingest = FakeIngest()
    source = default_source()
    poller = make_poller(source, ingest)
    await poller.tick()
    ids_first = [e["id"] for e in ingest.events]
    source.manifest = manifest(rows=5, runInfo={"runId": "run-2"})  # a new export run
    await poller.tick()
    assert poller.last_status.status == STATUS_OK
    ids_all = [e["id"] for e in ingest.events]
    assert ids_all == ids_first * 2  # deterministic: the ingest pipeline dedupes the replay


async def test_ids_do_not_depend_on_amount_or_batch_boundaries() -> None:
    a, b = FakeIngest(), FakeIngest()
    await make_poller(default_source(), a, batch_size=1).tick()
    other = FakeBlobSource(manifest(rows=None), {PART0: CSV0.replace("4.00", "9.99").encode()})
    await make_poller(other, b).tick()
    assert len(a.batches) == 3  # batch_size=1
    assert {e["id"] for e in b.events} <= {e["id"] for e in a.events}


async def test_blob_throttle_does_not_crash_and_is_retried() -> None:
    ingest = FakeIngest()
    source = default_source()
    source.error = RateLimitedError(retry_after_seconds=30)
    poller = make_poller(source, ingest)
    await poller.tick()
    assert poller.last_status.status == STATUS_READ_FAILED
    source.error = DependencyTransientError()
    await poller.tick()
    assert poller.last_status.status == STATUS_READ_FAILED
    source.error = None
    await poller.tick()
    assert poller.last_status.status == STATUS_OK
    assert ingest.events


async def test_ingest_5xx_does_not_crash_and_does_not_checkpoint() -> None:
    ingest = FakeIngest()
    poller = make_poller(default_source(), ingest)
    ingest.fail_status = 503
    await poller.tick()
    assert poller.last_status.status == STATUS_INGEST_FAILED
    ingest.fail_status = None
    await poller.tick()
    assert poller.last_status.status == STATUS_OK
    assert len(ingest.events) == 3


async def test_rejected_records_hold_the_checkpoint() -> None:
    ingest = FakeIngest()
    ingest.accept_limit = 1
    poller = make_poller(default_source(), ingest)
    await poller.tick()
    assert poller.last_status.status == STATUS_INGEST_FAILED
    ingest.accept_limit = None
    await poller.tick()
    assert poller.last_status.status == STATUS_OK


async def test_missing_partition_posts_what_exists_but_does_not_checkpoint() -> None:
    ingest = FakeIngest()
    source = FakeBlobSource(manifest(rows=None), {PART0: CSV0.encode()})  # PART1 absent
    poller = make_poller(source, ingest)
    await poller.tick()
    assert poller.last_status.status == STATUS_INCOMPLETE
    assert poller.last_status.blobs_missing == (PART1,)
    assert len(ingest.events) == 3
    source.blobs[PART1] = b"Date,CostInBillingCurrency,BillingCurrencyCode,ResourceId,MeterId\n"
    await poller.tick()  # the partition arrived: complete now, checkpointed
    assert poller.last_status.status == STATUS_OK
    await poller.tick()
    assert poller.last_status.status == STATUS_UNCHANGED


async def test_dateless_rows_are_reported_on_the_tick_status() -> None:
    ingest = FakeIngest()
    text = CSV0 + ",9.00,USD,/r9,m9\n"
    source = FakeBlobSource(manifest(rows=None, blobCount=1), {PART0: text.encode()})
    source.manifest = manifest([PART0], rows=None)
    poller = make_poller(source, ingest)
    await poller.tick()
    assert poller.last_status.rows_dropped_no_date == 1


def _split_month_source() -> FakeBlobSource:
    header = "Date,CostInBillingCurrency,BillingCurrencyCode,ResourceId,MeterId\n"
    csv = header + "2026-10-30,1.00,USD,/r/a,m1\n" + "2026-11-02,2.00,USD,/r/a,m1\n"
    return FakeBlobSource(manifest([PART0], rows=2), {PART0: csv.encode()})


async def test_previous_month_day_is_posted_current_month_day_is_held() -> None:
    ingest = FakeIngest()
    poller = make_poller(_split_month_source(), ingest)  # clock: 2026-11-19
    await poller.tick()
    assert poller.last_status.status == STATUS_OK
    assert poller.last_status.posted == 1
    assert poller.last_status.held_open_period == 1
    records = _records(ingest)
    assert [str(getattr(r.kind, "value", r.kind)) for r in records] == ["invoiced"]
    assert ingest.events[0]["data"]["billing_period"]["start_date"] == "2026-10-30"


async def test_held_days_post_once_the_month_closes_without_duplicates() -> None:
    from datetime import UTC, datetime

    now = [datetime(2026, 11, 19, tzinfo=UTC)]
    ingest = FakeIngest()
    poller = make_poller(_split_month_source(), ingest)
    poller._clock = lambda: now[0]
    await poller.tick()
    await poller.tick()  # same month, same manifest: skipped
    assert poller.last_status.status == STATUS_UNCHANGED
    assert len(ingest.events) == 1
    now[0] = datetime(2026, 12, 1, tzinfo=UTC)
    await poller.tick()
    assert poller.last_status.held_open_period == 0
    ids = [e["id"] for e in ingest.events]
    assert len(ids) == 3  # October day re-sent (deduped downstream) plus the now-closed day
    assert len(set(ids)) == 2
    await poller.tick()
    assert poller.last_status.status == STATUS_UNCHANGED


async def test_restated_closed_day_is_counted_and_not_posted() -> None:
    ingest = FakeIngest()
    source = default_source()
    poller = make_poller(source, ingest)
    await poller.tick()
    first = len(ingest.events)
    assert poller.last_status.restated == 0
    source.blobs[PART0] = CSV0.replace("4.00", "9.99").encode()
    source.manifest = manifest(rows=5, runInfo={"runId": "run-2"})
    await poller.tick()
    assert poller.last_status.status == STATUS_OK
    assert poller.last_status.restated == 1
    # Only the restated day is withheld; unchanged days re-post with the same ids (deduped).
    assert len(ingest.events) == first + (first - 1)
    assert "9.99" not in {r.amount.root for r in _records(ingest)}  # first amount wins


async def test_unchanged_reread_has_no_restatement_and_posts_nothing_new() -> None:
    ingest = FakeIngest()
    source = default_source()
    poller = make_poller(source, ingest)
    await poller.tick()
    ids = {e["id"] for e in ingest.events}
    source.manifest = manifest(rows=5, runInfo={"runId": "run-2"})
    await poller.tick()
    assert poller.last_status.restated == 0
    assert {e["id"] for e in ingest.events} == ids
