"""Versioned migration runner: plan (dry run), forward, rollback.

Safety model
* A lease is taken by compare-and-swap on the ledger before any write. A runner whose CAS loses,
  or that finds another owner's live lease, raises ``StaleVersionError`` and applies nothing.
* Idempotent: when the ledger shows nothing to do the runner returns without any write or
  lease. Documents already at (or past) the step version are skipped on forward.
* Every document write carries the etag it was read with; a document that changed underneath
  raises ``StaleVersionError`` and is never clobbered.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from neurosphere_core.errors import StaleVersionError
from neurosphere_core.migrations.lint import MigrationLintError, lint_migrations
from neurosphere_core.migrations.models import (
    AppliedStep,
    Lease,
    MigrationLedger,
    MigrationStep,
    MigrationTarget,
    ledger_id,
)
from neurosphere_core.migrations.protocols import StoredDocument

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from neurosphere_core.migrations.protocols import (
        AnalyticsSchemaStore,
        DocumentStore,
        LedgerStore,
    )

__all__ = ["MigrationResult", "MigrationRunner", "PlannedStep"]

Direction = Literal["forward", "rollback", "noop"]


@dataclass(frozen=True)
class PlannedStep:
    """A step the runner would apply and how many documents it would rewrite."""

    step_id: str
    version: int
    affected_documents: int


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of ``plan`` (``applied`` is empty, nothing written) or a real run."""

    direction: Direction
    from_version: int
    to_version: int
    steps: list[PlannedStep] = field(default_factory=list)
    documents_written: int = 0

    @property
    def noop(self) -> bool:
        return not self.steps


class _AnalyticsDocuments:
    """Adapts an ``AnalyticsSchemaStore`` to ``DocumentStore``: one schema is one document."""

    def __init__(self, store: AnalyticsSchemaStore, name: str) -> None:
        self._store = store
        self._name = name

    async def iter_documents(self) -> AsyncIterator[StoredDocument]:
        schema = await self._store.get_schema(self._name)
        doc = {**schema, "id": self._name, "schema_version": int(schema.get("schema_version", 0))}
        yield StoredDocument(doc, str(doc["schema_version"]))

    async def replace_document(self, document: dict[str, Any], *, etag: str) -> StoredDocument:
        await self._store.set_schema(self._name, document, expected_version=int(etag))
        return StoredDocument(document, str(document["schema_version"]))


class MigrationRunner:
    """Runs the steps of one (target, name) scope against its stores."""

    def __init__(
        self,
        *,
        target: MigrationTarget,
        name: str,
        steps: Iterable[MigrationStep],
        ledger_store: LedgerStore,
        document_store: DocumentStore | None = None,
        analytics_store: AnalyticsSchemaStore | None = None,
        owner: str | None = None,
        lease_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        scoped = sorted(
            (s for s in steps if s.target == target and s.name == name), key=lambda s: s.version
        )
        violations = lint_migrations(scoped)
        if violations:
            raise MigrationLintError(violations)
        if target == MigrationTarget.COSMOS_DOCUMENTS:
            if document_store is None:
                raise ValueError("cosmos_documents target needs document_store")
            self._docs: DocumentStore = document_store
        else:
            if analytics_store is None:
                raise ValueError("analytics_schema target needs analytics_store")
            self._docs = _AnalyticsDocuments(analytics_store, name)
        self._target = target
        self._name = name
        self._steps = scoped
        self._ledgers = ledger_store
        self._owner = owner or f"runner-{uuid.uuid4().hex[:8]}"
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ledger_id = ledger_id(target, name)

    @property
    def latest_version(self) -> int:
        return self._steps[-1].version if self._steps else 0

    # -- public API -------------------------------------------------------------------------

    async def plan(self, target_version: int | None = None) -> MigrationResult:
        """Dry run: ordered steps and affected-document counts. Writes nothing."""
        goal = self._goal(target_version)
        ledger = await self._ledgers.read(self._ledger_id)
        current = ledger.current_version if ledger else 0
        selected = self._select(current, goal)
        forward = goal >= current
        planned: list[PlannedStep] = []
        stored = await self._load()
        for step in selected:
            count = sum(1 for d in stored if self._needs(step, d.document, forward))
            planned.append(PlannedStep(step.id, step.version, count))
        return MigrationResult(self._direction(current, goal), current, goal, planned)

    async def migrate(self, target_version: int | None = None) -> MigrationResult:
        """Apply pending steps up to ``target_version`` (default: latest)."""
        goal = self._goal(target_version)
        return await self._run(goal, forward=True)

    async def rollback(self, target_version: int) -> MigrationResult:
        """Apply ``down`` in reverse order until the scope is at ``target_version``."""
        goal = self._goal(target_version)
        return await self._run(goal, forward=False)

    # -- internals --------------------------------------------------------------------------

    def _goal(self, target_version: int | None) -> int:
        goal = self.latest_version if target_version is None else target_version
        if goal < 0 or goal > self.latest_version:
            raise ValueError(f"target version {goal} outside 0..{self.latest_version}")
        return goal

    @staticmethod
    def _direction(current: int, goal: int) -> Direction:
        if goal > current:
            return "forward"
        return "rollback" if goal < current else "noop"

    def _select(self, current: int, goal: int) -> list[MigrationStep]:
        if goal > current:
            return [s for s in self._steps if current < s.version <= goal]
        return [s for s in reversed(self._steps) if goal < s.version <= current]

    @staticmethod
    def _needs(step: MigrationStep, doc: dict[str, Any], forward: bool) -> bool:
        version = int(doc.get("schema_version", 0))
        return version < step.version if forward else version >= step.version

    async def _load(self) -> list[StoredDocument]:
        return [d async for d in self._docs.iter_documents()]

    def _new_lease(self) -> Lease:
        return Lease(
            owner=self._owner, expires_at=self._clock() + timedelta(seconds=self._lease_seconds)
        )

    async def _run(self, goal: int, *, forward: bool) -> MigrationResult:
        ledger = await self._ledgers.read(self._ledger_id)
        current = ledger.current_version if ledger else 0
        if (forward and goal < current) or (not forward and goal > current):
            raise ValueError(
                f"cannot move {'forward' if forward else 'back'} from {current} to {goal}"
            )
        selected = self._select(current, goal)
        if not selected:
            return MigrationResult("noop", current, goal)
        if ledger is None:
            ledger = MigrationLedger(id=self._ledger_id, target=self._target, name=self._name)
        held = ledger.lease
        if held is not None and held.owner != self._owner and held.expires_at > self._clock():
            raise StaleVersionError(f"migration lease held by {held.owner}")
        # Lease CAS: the only way to start writing. A lost race raises StaleVersionError.
        ledger = await self._ledgers.write(
            ledger.model_copy(update={"lease": self._new_lease()}), expected_etag=ledger.etag
        )
        direction: Direction = "forward" if forward else "rollback"
        planned: list[PlannedStep] = []
        written = 0
        try:
            for step in selected:
                count = await self._apply_step(step, forward=forward)
                written += count
                planned.append(PlannedStep(step.id, step.version, count))
                ledger = await self._record(ledger, step, forward=forward)
        finally:
            await self._release(ledger)
        return MigrationResult(direction, current, goal, planned, written)

    async def _apply_step(self, step: MigrationStep, *, forward: bool) -> int:
        transform = step.up if forward else step.down
        if transform is None:  # lint rejects this; defence in depth
            raise MigrationLintError([])
        written = 0
        for stored in await self._load():
            if not self._needs(step, stored.document, forward):
                continue
            new_doc = transform(copy.deepcopy(stored.document))
            if new_doc.get("id") != stored.document["id"]:
                raise ValueError(f"step {step.id} must not change the document id")
            new_doc["schema_version"] = step.version if forward else step.version - 1
            await self._docs.replace_document(new_doc, etag=stored.etag)
            written += 1
        return written

    async def _record(
        self, ledger: MigrationLedger, step: MigrationStep, *, forward: bool
    ) -> MigrationLedger:
        if forward:
            applied = [
                *ledger.applied,
                AppliedStep(step_id=step.id, version=step.version, applied_at=self._clock()),
            ]
            version = step.version
        else:
            applied = [a for a in ledger.applied if a.version < step.version]
            version = step.version - 1
        updated = ledger.model_copy(
            update={"applied": applied, "current_version": version, "lease": self._new_lease()}
        )
        return await self._ledgers.write(updated, expected_etag=ledger.etag)

    async def _release(self, ledger: MigrationLedger) -> None:
        try:
            await self._ledgers.write(
                ledger.model_copy(update={"lease": None}), expected_etag=ledger.etag
            )
        except StaleVersionError:
            return  # lease expired and was taken over; nothing of ours left to release
