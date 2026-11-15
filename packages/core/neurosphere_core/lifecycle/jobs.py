"""Requested lifecycle jobs: the API persists them, the worker claims and records outcomes.

Job documents live in the existing ``lifecycle_requests`` container (partition key
``/customer_id``) beside the engine's blocked-request queue, marked by a ``job_state`` field.
The queue's ``pending()`` skips any document carrying ``job_state``; job documents use ids
prefixed ``job:`` before hashing, so they can never collide with a queued request id.

A job holds the request, the server-derived audit context (so the worker audits with the
requesting principal's identity, not its own) and, once run, the engine's outcome (metadata
only, never a record body).

States: ``pending`` (not yet picked up), ``queued`` (the engine deferred it, for example behind a
legal hold, and ``process_queue`` will run it later), ``done`` (a final outcome is recorded).
"""

from __future__ import annotations

import builtins
import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_core.audit.builders import AuditContext
from neurosphere_core.lifecycle.cosmos import (
    DEFAULT_REQUEST_CONTAINER,
    _invalid,  # pyright: ignore[reportPrivateUsage]
    _raise_mapped,  # pyright: ignore[reportPrivateUsage]
    _select,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.lifecycle.models import JobStatus, LifecycleOutcome, LifecycleRequest

__all__ = [
    "CosmosJobStore",
    "InMemoryJobStore",
    "JobState",
    "JobStore",
    "LifecycleJob",
    "job_checkpoint",
]

_JOB_FIELDS: Final = frozenset({"id", "customer_id", "job_state", "queued_key", "dedupe_key"})


class JobState(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    DONE = "done"


class LifecycleJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: LifecycleRequest
    ctx: AuditContext
    #: Requested dry-run. A job can only make a run safer; it never overrides the engine mode.
    dry_run: bool = False
    #: Server-derived principal pseudonym of the requester (never client-supplied).
    requested_by: str
    submitted_at: datetime
    state: JobState = JobState.PENDING
    outcome: LifecycleOutcome | None = None
    updated_at: datetime | None = None

    @property
    def job_id(self) -> str:
        return self.request.request_id


def job_checkpoint(job: LifecycleJob) -> str:
    """Sortable claim key: submission time then id."""
    stamp = job.submitted_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return f"job|{stamp}|{job.job_id}"


def _state_for(outcome: LifecycleOutcome) -> JobState:
    return JobState.QUEUED if outcome.status is JobStatus.QUEUED else JobState.DONE


@runtime_checkable
class JobStore(Protocol):
    async def submit(self, job: LifecycleJob) -> tuple[LifecycleJob, bool]:
        """Persist ``job``. When an equal request is already pending or queued, return that job
        and ``False`` instead of creating a duplicate."""
        ...

    async def get(self, job_id: str) -> LifecycleJob | None: ...

    async def list(self, *, limit: int = 50) -> builtins.list[LifecycleJob]:
        """Most recent jobs first, bounded."""
        ...

    async def claim(self, checkpoint: str | None, limit: int) -> builtins.list[LifecycleJob]:
        """Pending jobs after ``checkpoint`` in submission order."""
        ...

    async def record_outcome(self, job_id: str, outcome: LifecycleOutcome) -> bool:
        """Attach ``outcome`` to the job; ``False`` when no such job exists (a sweep outcome)."""
        ...

    async def depth(self) -> int:
        """Jobs not yet final (pending or queued)."""
        ...


class InMemoryJobStore:
    def __init__(self, *, clock: Any = None) -> None:
        self._jobs: dict[str, LifecycleJob] = {}
        self._clock = clock or (lambda: datetime.now(UTC))

    async def submit(self, job: LifecycleJob) -> tuple[LifecycleJob, bool]:
        key = job.request.dedupe_key
        for existing in self._jobs.values():
            if existing.state is not JobState.DONE and existing.request.dedupe_key == key:
                return existing, False
        self._jobs[job.job_id] = job
        return job, True

    async def get(self, job_id: str) -> LifecycleJob | None:
        return self._jobs.get(job_id)

    async def list(self, *, limit: int = 50) -> builtins.list[LifecycleJob]:
        ordered = sorted(self._jobs.values(), key=job_checkpoint, reverse=True)
        return ordered[:limit]

    async def claim(self, checkpoint: str | None, limit: int) -> builtins.list[LifecycleJob]:
        ordered = sorted(
            (j for j in self._jobs.values() if j.state is JobState.PENDING), key=job_checkpoint
        )
        if checkpoint:
            ordered = [j for j in ordered if job_checkpoint(j) > checkpoint]
        return ordered[:limit]

    async def record_outcome(self, job_id: str, outcome: LifecycleOutcome) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        self._jobs[job_id] = job.model_copy(
            update={"outcome": outcome, "state": _state_for(outcome), "updated_at": self._clock()}
        )
        return True

    async def depth(self) -> int:
        return sum(1 for j in self._jobs.values() if j.state is not JobState.DONE)


def _doc_id(job_id: str) -> str:
    return hashlib.sha256(f"job:{job_id}".encode()).hexdigest()


def _from_row(row: Any) -> LifecycleJob:
    body = {k: v for k, v in row.items() if not k.startswith("_") and k not in _JOB_FIELDS}
    try:
        return LifecycleJob.model_validate(body)
    except ValidationError as exc:
        raise _invalid(exc) from exc


class CosmosJobStore:
    """:class:`JobStore` for one customer over the ``lifecycle_requests`` container."""

    def __init__(self, container: ContainerProxy, *, customer_id: str) -> None:
        self._container = container
        self._customer = customer_id

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        customer_id: str,
        container: str = DEFAULT_REQUEST_CONTAINER,
    ) -> CosmosJobStore:
        return cls(
            client.get_database_client(database).get_container_client(container),
            customer_id=customer_id,
        )

    def _body(self, job: LifecycleJob) -> dict[str, Any]:
        return {
            **job.model_dump(mode="json"),
            "id": _doc_id(job.job_id),
            "customer_id": self._customer,
            "job_state": job.state.value,
            # Present so the queue's ordered query stays valid; the queue skips job documents.
            "queued_key": job_checkpoint(job),
            "dedupe_key": job.request.dedupe_key,
        }

    async def submit(self, job: LifecycleJob) -> tuple[LifecycleJob, bool]:
        for state in (JobState.PENDING, JobState.QUEUED):
            rows = await _select(
                self._container,
                "SELECT * FROM c WHERE c.customer_id = @customer AND c.dedupe_key = @key "
                "AND c.job_state = @state",
                [
                    {"name": "@customer", "value": self._customer},
                    {"name": "@key", "value": job.request.dedupe_key},
                    {"name": "@state", "value": state.value},
                ],
                self._customer,
            )
            if rows:
                return _from_row(rows[0]), False
        try:
            await self._container.upsert_item(body=self._body(job))
        except Exception as exc:
            _raise_mapped(exc)
        return job, True

    async def get(self, job_id: str) -> LifecycleJob | None:
        try:
            row = await self._container.read_item(
                item=_doc_id(job_id), partition_key=self._customer
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def list(self, *, limit: int = 50) -> builtins.list[LifecycleJob]:
        rows = await _select(
            self._container,
            "SELECT TOP @n * FROM c WHERE c.customer_id = @customer AND IS_DEFINED(c.job_state) "
            "ORDER BY c.queued_key DESC",
            [
                {"name": "@n", "value": max(1, limit)},
                {"name": "@customer", "value": self._customer},
            ],
            self._customer,
        )
        return [_from_row(r) for r in rows]

    async def claim(self, checkpoint: str | None, limit: int) -> builtins.list[LifecycleJob]:
        rows = await _select(
            self._container,
            "SELECT TOP @n * FROM c WHERE c.customer_id = @customer AND c.job_state = @state "
            "AND c.queued_key > @after ORDER BY c.queued_key ASC",
            [
                {"name": "@n", "value": max(1, limit)},
                {"name": "@customer", "value": self._customer},
                {"name": "@state", "value": JobState.PENDING.value},
                {"name": "@after", "value": checkpoint or ""},
            ],
            self._customer,
        )
        return [_from_row(r) for r in rows]

    async def record_outcome(self, job_id: str, outcome: LifecycleOutcome) -> bool:
        job = await self.get(job_id)
        if job is None:
            return False
        updated = job.model_copy(
            update={
                "outcome": outcome,
                "state": _state_for(outcome),
                "updated_at": datetime.now(UTC),
            }
        )
        try:
            await self._container.upsert_item(body=self._body(updated))
        except Exception as exc:
            _raise_mapped(exc)
        return True

    async def depth(self) -> int:
        count = 0
        for state in (JobState.PENDING, JobState.QUEUED):
            rows = await _select(
                self._container,
                "SELECT c.id FROM c WHERE c.customer_id = @customer AND c.job_state = @state",
                [
                    {"name": "@customer", "value": self._customer},
                    {"name": "@state", "value": state.value},
                ],
                self._customer,
            )
            count += len(rows)
        return count
