"""Read-back verification and the worker loop for lifecycle jobs."""

from __future__ import annotations

import hashlib
import itertools
from datetime import UTC, datetime, timedelta

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext, AuditRepository, InMemoryAuditStore
from neurosphere_core.lifecycle import (
    ActionKind,
    JobStatus,
    LegalHold,
    LifecycleEngine,
    LifecycleOutcome,
    LifecycleRequest,
    TargetRecord,
    TargetRef,
    TargetRegistry,
    load_policy,
)
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryRequestQueue,
    InMemoryTarget,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.lifecycle import LifecycleWorker, RequestedJob, SweepSpec
from neurosphere_workers.runtime.worker import Batch, BatchOutcome

CHAIN = "lifecycle.contoso"
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
POLICY = {
    "policy_version": "records-2026-1",
    "retain_prompt_response_bodies": False,
    "rules": [{"data_class": "telemetry", "min_retention_days": 1, "max_retention_days": 30}],
}


def _ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-worker-01",
                "principal_kind": "service_principal",
            },
            "roles": [],
            "allowed_domains": ["commercial:contoso:catalog:domain:retail"],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"w").hexdigest(),
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-w1", operation="lifecycle.run", channel="worker"
    )


def _rec(rid: str, age_days: int) -> TargetRecord:
    return TargetRecord(
        record_id=rid, data_class="telemetry", created_at=NOW - timedelta(days=age_days)
    )


def _build(*, ignore_deletes: bool = False):
    counter = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: NOW,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    target = InMemoryTarget("archive", "blobs", ignore_deletes=ignore_deletes)
    registry = TargetRegistry()
    registry.register(target)
    holds = InMemoryHoldRegistry()
    engine = LifecycleEngine(
        policy=load_policy(POLICY),
        targets=registry,
        holds=holds,
        queue=InMemoryRequestQueue(),
        audit=audit,
        audit_chain_id=CHAIN,
        cloud="commercial",
        customer_id="contoso",
        clock=lambda: NOW,
    )
    return engine, audit, target, holds


class _Source:
    def __init__(self, jobs: list[RequestedJob]) -> None:
        self._jobs = jobs

    async def next_jobs(self, checkpoint: str | None, limit: int) -> list[RequestedJob]:
        done = int(checkpoint or 0)
        return self._jobs[done : done + limit]


def _delete(rid: str) -> LifecycleRequest:
    return LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="archive", container="blobs", record_id=rid),
    )


async def test_readback_success_completes_and_audits_verified() -> None:
    engine, audit, target, _ = _build()
    target.put(_rec("b1", 10))
    out = await engine.submit(_delete("b1"), _ctx())
    assert out.status is JobStatus.COMPLETED
    assert out.verified
    assert await target.get("b1") is None
    records = await audit.read_range(CHAIN, limit=10)
    assert [r.kind for r in records] == ["before", "after"]
    assert records[-1].outcome is not None
    assert records[-1].outcome.result == "succeeded"
    assert records[-1].outcome.verified is True


async def test_readback_still_finds_target_marks_failed_and_audits() -> None:
    engine, audit, target, _ = _build(ignore_deletes=True)
    target.put(_rec("b1", 10))
    out = await engine.submit(_delete("b1"), _ctx())
    assert out.status is JobStatus.FAILED
    assert out.reason == "readback_found_target"
    assert not out.verified
    assert "b1" in target.records
    records = await audit.read_range(CHAIN, limit=10)
    last = records[-1]
    assert last.kind == "after"
    assert last.outcome is not None
    assert last.outcome.result == "failed"
    assert last.outcome.verified is False
    assert last.outcome.detail == "readback_found_target"


async def test_worker_runs_requested_jobs_and_reports_failures() -> None:
    engine, _, target, _ = _build()
    target.put(_rec("b1", 10))
    seen: list[LifecycleOutcome] = []

    async def sink(o: LifecycleOutcome) -> None:
        seen.append(o)

    worker = LifecycleWorker(
        engine,
        _Source([RequestedJob(_delete("b1"), _ctx(), "1")]),
        clock=lambda: NOW,
        on_outcome=sink,
    )
    batch = await worker.fetch_batch(None)
    assert batch is not None
    assert batch.checkpoint == "1"
    assert await worker.process_batch(batch) is BatchOutcome.ACCEPTED
    assert [o.status for o in seen] == [JobStatus.COMPLETED]
    assert await target.get("b1") is None


async def test_worker_counts_failed_verification_and_still_accepts_batch() -> None:
    engine, _, target, _ = _build(ignore_deletes=True)
    target.put(_rec("b1", 10))
    worker = LifecycleWorker(
        engine, _Source([RequestedJob(_delete("b1"), _ctx(), "1")]), clock=lambda: NOW
    )
    batch = await worker.fetch_batch(None)
    assert batch is not None
    assert await worker.process_batch(batch) is BatchOutcome.ACCEPTED
    assert worker.outcomes_failed == 1


async def test_worker_scheduled_sweep_expires_and_respects_hold() -> None:
    engine, _, target, holds = _build()
    target.put(_rec("old", 90))
    target.put(_rec("held", 90))
    target.put(_rec("young", 5))
    await holds.place(LegalHold(reason_code="litigation", record_id="held", placed_at=NOW))
    worker = LifecycleWorker(
        engine,
        _Source([]),
        sweeps=[SweepSpec(target=target, data_class="telemetry")],
        sweep_ctx=_ctx(),
        clock=lambda: NOW,
    )
    batch = await worker.fetch_batch(None)
    assert batch is not None
    assert batch.items == ()
    await worker.process_batch(batch)
    assert "old" not in target.records
    assert "held" in target.records
    assert "young" in target.records
    # next fetch within the interval is idle
    assert await worker.fetch_batch(batch.checkpoint) is None


async def test_worker_retries_queue_after_hold_release() -> None:
    engine, _, target, holds = _build()
    target.put(_rec("held", 90))
    hold = LegalHold(reason_code="litigation", record_id="held", placed_at=NOW)
    await holds.place(hold)
    worker = LifecycleWorker(
        engine, _Source([RequestedJob(_delete("held"), _ctx(), "1")]), clock=lambda: NOW
    )
    batch = await worker.fetch_batch(None)
    assert batch is not None
    await worker.process_batch(batch)
    assert "held" in target.records
    await holds.release(hold.hold_id)
    await worker.process_batch(Batch(items=(), checkpoint="1"))
    assert "held" not in target.records
