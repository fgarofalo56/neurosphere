"""In-memory runner tests: forward/rollback, idempotency, dry run, lease races, analytics."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.migrations import (
    InMemoryAnalyticsSchemaStore,
    InMemoryDocumentStore,
    InMemoryLedgerStore,
    Lease,
    MigrationLedger,
    MigrationLintError,
    MigrationRunner,
    MigrationStep,
    MigrationTarget,
    ledger_id,
    snapshot_hash,
    synthetic_snapshot,
)
from neurosphere_core.migrations.sample_steps import sample_steps

NAME = "models"
DOCS = 6


def make(
    docs: InMemoryDocumentStore, ledgers: InMemoryLedgerStore, owner: str = "r1"
) -> MigrationRunner:
    return MigrationRunner(
        target=MigrationTarget.COSMOS_DOCUMENTS,
        name=NAME,
        steps=sample_steps(NAME),
        ledger_store=ledgers,
        document_store=docs,
        owner=owner,
    )


def fresh() -> tuple[InMemoryDocumentStore, InMemoryLedgerStore]:
    return InMemoryDocumentStore(synthetic_snapshot(DOCS)), InMemoryLedgerStore()


async def test_forward_then_rollback_restores_snapshot() -> None:
    docs, ledgers = fresh()
    before = snapshot_hash(docs.snapshot())
    runner = make(docs, ledgers)

    result = await runner.migrate()
    assert result.direction == "forward"
    assert result.documents_written == DOCS * 2
    migrated = docs.snapshot()
    assert all(d["schema_version"] == 2 and "legacy_label" not in d for d in migrated)
    assert snapshot_hash(migrated) != before

    back = await runner.rollback(0)
    assert back.direction == "rollback"
    assert snapshot_hash(docs.snapshot()) == before
    ledger = await ledgers.read(ledger_id(MigrationTarget.COSMOS_DOCUMENTS, NAME))
    assert ledger is not None
    assert ledger.current_version == 0
    assert ledger.applied == []
    assert ledger.lease is None


async def test_partial_target_and_partial_rollback() -> None:
    docs, ledgers = fresh()
    runner = make(docs, ledgers)
    await runner.migrate(1)
    assert {d["schema_version"] for d in docs.snapshot()} == {1}
    assert all("legacy_label" in d and "label" in d for d in docs.snapshot())
    await runner.migrate(2)
    await runner.rollback(1)
    assert {d["schema_version"] for d in docs.snapshot()} == {1}


async def test_second_forward_is_noop_with_zero_writes() -> None:
    docs, ledgers = fresh()
    runner = make(docs, ledgers)
    await runner.migrate()
    doc_writes, ledger_writes = docs.replace_count, ledgers.write_count

    again = await runner.migrate()
    assert again.noop
    assert again.documents_written == 0
    assert docs.replace_count == doc_writes
    assert ledgers.write_count == ledger_writes


async def test_documents_already_at_version_are_skipped() -> None:
    # Simulates a crash after documents were rewritten but before the ledger recorded the step.
    docs, ledgers = fresh()
    await make(docs, ledgers).migrate(1)
    ledgers_after = InMemoryLedgerStore()  # ledger lost; documents already at version 1
    result = await make(docs, ledgers_after).migrate(1)
    assert result.documents_written == 0
    assert {d["schema_version"] for d in docs.snapshot()} == {1}


async def test_dry_run_writes_nothing() -> None:
    docs, ledgers = fresh()
    before = snapshot_hash(docs.snapshot())
    plan = await make(docs, ledgers).plan()
    assert [(s.version, s.affected_documents) for s in plan.steps] == [(1, DOCS), (2, DOCS)]
    assert docs.replace_count == 0
    assert ledgers.write_count == 0
    assert snapshot_hash(docs.snapshot()) == before


async def test_concurrent_runners_exactly_one_applies() -> None:
    docs, ledgers = fresh()
    outcomes = await asyncio.gather(
        make(docs, ledgers, "a").migrate(),
        make(docs, ledgers, "b").migrate(),
        return_exceptions=True,
    )
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], StaleVersionError)
    assert losers[0].code == "stale_version"
    assert docs.replace_count == DOCS * 2  # each step applied exactly once per document
    ledger = await ledgers.read(ledger_id(MigrationTarget.COSMOS_DOCUMENTS, NAME))
    assert ledger is not None
    assert [a.version for a in ledger.applied] == [1, 2]


async def test_live_lease_of_another_owner_blocks() -> None:
    docs, ledgers = fresh()
    lid = ledger_id(MigrationTarget.COSMOS_DOCUMENTS, NAME)
    lease = Lease(owner="other", expires_at=datetime.now(UTC) + timedelta(minutes=5))
    await ledgers.write(
        MigrationLedger(id=lid, target=MigrationTarget.COSMOS_DOCUMENTS, name=NAME, lease=lease),
        expected_etag=None,
    )
    with pytest.raises(StaleVersionError):
        await make(docs, ledgers).migrate()
    assert docs.replace_count == 0


async def test_expired_lease_is_taken_over() -> None:
    docs, ledgers = fresh()
    lid = ledger_id(MigrationTarget.COSMOS_DOCUMENTS, NAME)
    lease = Lease(owner="dead", expires_at=datetime.now(UTC) - timedelta(minutes=5))
    await ledgers.write(
        MigrationLedger(id=lid, target=MigrationTarget.COSMOS_DOCUMENTS, name=NAME, lease=lease),
        expected_etag=None,
    )
    result = await make(docs, ledgers).migrate()
    assert result.documents_written == DOCS * 2


async def test_document_changed_underneath_is_not_clobbered() -> None:
    docs, ledgers = fresh()
    original_replace = docs.replace_document
    tampered = False

    async def replace(document: dict[str, object], *, etag: str):  # type: ignore[no-untyped-def]
        nonlocal tampered
        if not tampered:
            tampered = True
            docs.mutate_behind_runner("doc-0000", name="edited-by-someone-else")
        return await original_replace(document, etag=etag)

    docs.replace_document = replace  # type: ignore[method-assign]
    with pytest.raises(StaleVersionError):
        await make(docs, ledgers).migrate()
    first = docs.snapshot()[0]
    assert first["name"] == "edited-by-someone-else"
    assert first["schema_version"] == 0
    ledger = await ledgers.read(ledger_id(MigrationTarget.COSMOS_DOCUMENTS, NAME))
    assert ledger is not None
    assert ledger.lease is None  # released even though the run failed


async def test_out_of_range_target_rejected() -> None:
    docs, ledgers = fresh()
    with pytest.raises(ValueError, match="outside"):
        await make(docs, ledgers).migrate(3)


async def test_runner_rejects_lint_violations() -> None:
    steps = sample_steps(NAME)
    bad = steps[1].model_copy(update={"release": "0.2.0"})
    with pytest.raises(MigrationLintError):
        MigrationRunner(
            target=MigrationTarget.COSMOS_DOCUMENTS,
            name=NAME,
            steps=[steps[0], bad],
            ledger_store=InMemoryLedgerStore(),
            document_store=InMemoryDocumentStore(),
        )


async def test_step_must_not_change_document_id() -> None:
    step = MigrationStep(
        id="s1",
        version=1,
        target=MigrationTarget.COSMOS_DOCUMENTS,
        name=NAME,
        description="bad",
        release="0.2.0",
        up=lambda d: {**d, "id": "other"},
        down=lambda d: d,
    )
    docs, ledgers = fresh()
    runner = MigrationRunner(
        target=MigrationTarget.COSMOS_DOCUMENTS,
        name=NAME,
        steps=[step],
        ledger_store=ledgers,
        document_store=docs,
    )
    with pytest.raises(ValueError, match="document id"):
        await runner.migrate()


async def test_analytics_schema_forward_rollback_and_noop() -> None:
    schemas = {"co_usage": {"schema_version": 0, "legacy_label": "x", "columns": ["a"]}}
    store = InMemoryAnalyticsSchemaStore(schemas)
    ledgers = InMemoryLedgerStore()
    runner = MigrationRunner(
        target=MigrationTarget.ANALYTICS_SCHEMA,
        name="co_usage",
        steps=sample_steps("co_usage", MigrationTarget.ANALYTICS_SCHEMA),
        ledger_store=ledgers,
        analytics_store=store,
    )
    before = await store.get_schema("co_usage")
    await runner.migrate()
    assert await store.get_schema_version("co_usage") == 2
    writes = store.set_count
    assert (await runner.migrate()).noop
    assert store.set_count == writes
    await runner.rollback(0)
    restored = await store.get_schema("co_usage")
    restored.pop("id", None)
    before.pop("id", None)
    assert snapshot_hash([{"id": "x", **restored}]) == snapshot_hash([{"id": "x", **before}])


async def test_analytics_concurrent_runners_one_loses() -> None:
    store = InMemoryAnalyticsSchemaStore({"s": {"schema_version": 0, "legacy_label": "x"}})
    ledgers = InMemoryLedgerStore()

    def runner(owner: str) -> MigrationRunner:
        return MigrationRunner(
            target=MigrationTarget.ANALYTICS_SCHEMA,
            name="s",
            steps=sample_steps("s", MigrationTarget.ANALYTICS_SCHEMA),
            ledger_store=ledgers,
            analytics_store=store,
            owner=owner,
        )

    outcomes = await asyncio.gather(
        runner("a").migrate(), runner("b").migrate(), return_exceptions=True
    )
    assert sum(isinstance(o, StaleVersionError) for o in outcomes) == 1
    assert store.set_count == 2


def test_runner_requires_matching_store() -> None:
    with pytest.raises(ValueError, match="document_store"):
        MigrationRunner(
            target=MigrationTarget.COSMOS_DOCUMENTS,
            name=NAME,
            steps=[],
            ledger_store=InMemoryLedgerStore(),
        )
    with pytest.raises(ValueError, match="analytics_store"):
        MigrationRunner(
            target=MigrationTarget.ANALYTICS_SCHEMA,
            name=NAME,
            steps=[],
            ledger_store=InMemoryLedgerStore(),
        )
