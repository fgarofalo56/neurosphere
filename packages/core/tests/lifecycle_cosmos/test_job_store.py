"""Requested-job store: in-memory and Cosmos (in-process fake) behave the same."""

from __future__ import annotations

from datetime import timedelta

import pytest
from hitl_cosmos.fake_container import FakeContainer  # pyright: ignore[reportMissingImports]
from neurosphere_core.lifecycle import (
    ActionKind,
    JobStatus,
    LifecycleOutcome,
    LifecycleRequest,
    TargetRef,
)
from neurosphere_core.lifecycle.cosmos import LIFECYCLE_PARTITION_KEY_PATH, CosmosRequestQueue
from neurosphere_core.lifecycle.jobs import (
    CosmosJobStore,
    InMemoryJobStore,
    JobState,
    JobStore,
    LifecycleJob,
    job_checkpoint,
)

from .contract import CUSTOMER, NOW, make_ctx, make_queued


def _job(record_id: str, *, minutes: int = 0, dry_run: bool = False) -> LifecycleJob:
    return LifecycleJob(
        request=LifecycleRequest(
            request_id=f"job-{record_id}",
            action=ActionKind.DELETE,
            target=TargetRef(target_kind="catalog", container="records", record_id=record_id),
        ),
        ctx=make_ctx(),
        dry_run=dry_run,
        requested_by="p-7f3a9c21",
        submitted_at=NOW + timedelta(minutes=minutes),
    )


def _outcome(job: LifecycleJob, status: JobStatus, reason: str, **kw: object) -> LifecycleOutcome:
    return LifecycleOutcome.model_validate(
        {
            "request_id": job.job_id,
            "action": job.request.action,
            "status": status,
            "reason": reason,
            **kw,
        }
    )


@pytest.fixture(params=["memory", "cosmos-fake"])
def store(request: pytest.FixtureRequest) -> JobStore:
    if request.param == "memory":
        return InMemoryJobStore()
    container = FakeContainer((LIFECYCLE_PARTITION_KEY_PATH,))
    return CosmosJobStore(container, customer_id=CUSTOMER)  # type: ignore[arg-type]


async def test_submit_get_round_trip(store: JobStore) -> None:
    job = _job("a", dry_run=True)
    stored, created = await store.submit(job)
    assert created is True
    got = await store.get("job-a")
    assert got is not None
    assert got.state is JobState.PENDING
    assert got.dry_run is True
    assert got.requested_by == "p-7f3a9c21"
    assert got.request == job.request
    assert await store.get("missing") is None
    assert stored.job_id == "job-a"


async def test_equal_pending_request_is_deduplicated(store: JobStore) -> None:
    first, created1 = await store.submit(_job("a"))
    dup = LifecycleJob.model_validate(
        {**_job("a").model_dump(), "request": {**_job("a").request.model_dump(), "request_id": "x"}}
    )
    second, created2 = await store.submit(dup)
    assert (created1, created2) == (True, False)
    assert second.job_id == first.job_id
    assert await store.get("x") is None


async def test_claim_is_ordered_and_resumes_after_checkpoint(store: JobStore) -> None:
    for i, rid in enumerate(["a", "b", "c"]):
        await store.submit(_job(rid, minutes=i))
    first = await store.claim(None, 2)
    assert [j.job_id for j in first] == ["job-a", "job-b"]
    rest = await store.claim(job_checkpoint(first[-1]), 10)
    assert [j.job_id for j in rest] == ["job-c"]


async def test_record_outcome_moves_state_and_stops_claiming(store: JobStore) -> None:
    job = _job("a")
    await store.submit(job)
    assert await store.depth() == 1
    assert await store.record_outcome("job-a", _outcome(job, JobStatus.QUEUED, "legal_hold"))
    got = await store.get("job-a")
    assert got is not None and got.state is JobState.QUEUED
    assert await store.claim(None, 10) == []
    assert await store.depth() == 1
    done = _outcome(job, JobStatus.COMPLETED, "deleted", effect="deleted", verified=True)
    assert await store.record_outcome("job-a", done)
    got = await store.get("job-a")
    assert got is not None
    assert got.state is JobState.DONE
    assert got.outcome is not None and got.outcome.status is JobStatus.COMPLETED
    assert await store.depth() == 0
    assert await store.record_outcome("nope", done) is False


async def test_completed_job_does_not_block_a_new_equal_request(store: JobStore) -> None:
    job = _job("a")
    await store.submit(job)
    await store.record_outcome("job-a", _outcome(job, JobStatus.COMPLETED, "deleted"))
    again = LifecycleJob.model_validate(
        {**job.model_dump(), "request": {**job.request.model_dump(), "request_id": "job-a2"}}
    )
    _, created = await store.submit(again)
    assert created is True


async def test_list_is_newest_first_and_bounded(store: JobStore) -> None:
    for i, rid in enumerate(["a", "b", "c"]):
        await store.submit(_job(rid, minutes=i))
    listed = await store.list(limit=2)
    assert [j.job_id for j in listed] == ["job-c", "job-b"]


async def test_jobs_share_the_queue_container_without_leaking_into_the_queue() -> None:
    container = FakeContainer((LIFECYCLE_PARTITION_KEY_PATH,))
    jobs = CosmosJobStore(container, customer_id=CUSTOMER)  # type: ignore[arg-type]
    queue = CosmosRequestQueue(container, customer_id=CUSTOMER)  # type: ignore[arg-type]
    await jobs.submit(_job("a"))
    item = make_queued("c-1")
    assert await queue.enqueue(item) is True
    assert [q.request.request_id for q in await queue.pending()] == [item.request.request_id]
    await queue.remove(item.request.request_id)
    assert await jobs.get("job-a") is not None  # removing a queued request never touches a job
    assert [d["job_state"] for d in container.docs.values()] == ["pending"]


async def test_job_store_is_confined_to_its_customer_partition() -> None:
    container = FakeContainer((LIFECYCLE_PARTITION_KEY_PATH,))
    mine = CosmosJobStore(container, customer_id="contoso")  # type: ignore[arg-type]
    theirs = CosmosJobStore(container, customer_id="fabrikam")  # type: ignore[arg-type]
    await mine.submit(_job("a"))
    assert await theirs.get("job-a") is None
    assert await theirs.claim(None, 10) == []
    assert await theirs.list() == []
    assert all(partition is not None for _, _, partition in container.queries)
