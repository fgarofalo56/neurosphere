"""The store-backed job source and outcome sink: submit, claim, run, record."""

from __future__ import annotations

import hashlib
import itertools
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext, AuditRepository, InMemoryAuditStore
from neurosphere_core.lifecycle import (
    ActionKind,
    JobStatus,
    LifecycleEngine,
    LifecycleRequest,
    TargetRecord,
    TargetRef,
    TargetRegistry,
    load_policy,
)
from neurosphere_core.lifecycle.jobs import InMemoryJobStore, JobState, LifecycleJob
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryRequestQueue,
    InMemoryTarget,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.lifecycle import LifecycleWorker
from neurosphere_workers.lifecycle.job_source import StoreJobSource, outcome_sink

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
CHAIN = "lifecycle.contoso"
POLICY = {
    "policy_version": "p1",
    "retain_prompt_response_bodies": False,
    "rules": [{"data_class": "telemetry", "min_retention_days": 0, "max_retention_days": 30}],
}


def _ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-requester",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"r").hexdigest(),
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-job", operation="lifecycle.request.submit", channel="worker"
    )


def _job(rid: str, *, minutes: int = 0, dry_run: bool = False) -> LifecycleJob:
    return LifecycleJob(
        request=LifecycleRequest(
            request_id=f"job-{rid}",
            action=ActionKind.DELETE,
            target=TargetRef(target_kind="archive", container="blobs", record_id=rid),
        ),
        ctx=_ctx(),
        dry_run=dry_run,
        requested_by="p-requester",
        submitted_at=NOW + timedelta(minutes=minutes),
    )


def _rig(mode: str):  # type: ignore[no-untyped-def]
    counter = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: NOW,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    target = InMemoryTarget("archive", "blobs")
    registry = TargetRegistry()
    registry.register(target)
    jobs = InMemoryJobStore()
    engine = LifecycleEngine(
        policy=load_policy(POLICY),
        targets=registry,
        holds=InMemoryHoldRegistry(),
        queue=InMemoryRequestQueue(),
        audit=audit,
        audit_chain_id=CHAIN,
        cloud="commercial",
        customer_id="contoso",
        clock=lambda: NOW,
        mode=mode,  # type: ignore[arg-type]
    )
    worker = LifecycleWorker(
        engine, StoreJobSource(jobs), clock=lambda: NOW, on_outcome=outcome_sink(jobs)
    )
    return worker, jobs, target, audit


def _put(target: InMemoryTarget, rid: str) -> None:
    target.put(
        TargetRecord(record_id=rid, data_class="telemetry", created_at=NOW - timedelta(days=5))
    )


async def _run_once(worker: LifecycleWorker, checkpoint: str | None = None) -> str | None:
    batch = await worker.fetch_batch(checkpoint)
    assert batch is not None
    await worker.process_batch(batch)
    return batch.checkpoint


async def test_source_yields_pending_jobs_in_order_with_their_context() -> None:
    jobs = InMemoryJobStore()
    await jobs.submit(_job("b", minutes=1))
    await jobs.submit(_job("a", minutes=0, dry_run=True))
    got = await StoreJobSource(jobs).next_jobs(None, 10)
    assert [j.request.request_id for j in got] == ["job-a", "job-b"]
    assert [j.dry_run for j in got] == [True, False]
    assert got[0].ctx.actor.principal_pseudonym  # the requester's context, carried to the worker
    after = await StoreJobSource(jobs).next_jobs(got[0].checkpoint, 10)
    assert [j.request.request_id for j in after] == ["job-b"]


async def test_a_submitted_job_runs_to_an_outcome_visible_on_the_job_in_execute_mode() -> None:
    worker, jobs, target, _ = _rig("execute")
    _put(target, "b1")
    await jobs.submit(_job("b1"))
    await _run_once(worker)
    job = await jobs.get("job-b1")
    assert job is not None
    assert job.state is JobState.DONE
    assert job.outcome is not None
    assert (job.outcome.status, job.outcome.effect.value) == (JobStatus.COMPLETED, "deleted")
    assert "b1" not in target.records


async def test_dry_run_default_leaves_targets_intact_and_says_so() -> None:
    worker, jobs, target, audit = _rig("dry_run")
    _put(target, "b1")
    await jobs.submit(_job("b1"))
    await _run_once(worker)
    job = await jobs.get("job-b1")
    assert job is not None and job.outcome is not None
    assert job.state is JobState.DONE
    assert job.outcome.dry_run is True
    assert job.outcome.reason == "dry_run:would_delete"
    assert "b1" in target.records
    assert target.delete_calls == 0
    details = [r.outcome.detail for r in await audit.read_range(CHAIN, limit=10) if r.outcome]
    assert details == ["dry_run:would_delete"]


async def test_a_job_can_request_dry_run_in_execute_mode() -> None:
    worker, jobs, target, _ = _rig("execute")
    _put(target, "b1")
    await jobs.submit(_job("b1", dry_run=True))
    await _run_once(worker)
    assert "b1" in target.records


async def test_the_worker_resumes_after_its_checkpoint_and_does_not_rerun_done_jobs() -> None:
    worker, jobs, target, _ = _rig("execute")
    for rid in ("b1", "b2"):
        _put(target, rid)
    await jobs.submit(_job("b1", minutes=0))
    checkpoint = await _run_once(worker)
    await jobs.submit(_job("b2", minutes=1))
    await _run_once(worker, checkpoint)
    assert target.records == {}
    assert target.delete_calls == 2


async def test_an_unknown_target_is_refused_and_recorded_on_the_job() -> None:
    worker, jobs, _, _ = _rig("execute")
    bad = LifecycleJob(
        request=LifecycleRequest(
            request_id="job-x",
            action=ActionKind.DELETE,
            target=TargetRef(target_kind="catalog", container="nope", record_id="r"),
        ),
        ctx=_ctx(),
        requested_by="p-requester",
        submitted_at=NOW,
    )
    await jobs.submit(bad)
    await _run_once(worker)
    job = await jobs.get("job-x")
    assert job is not None and job.outcome is not None
    assert (job.state, job.outcome.status, job.outcome.reason) == (
        JobState.DONE,
        JobStatus.REFUSED,
        "unknown_target",
    )
