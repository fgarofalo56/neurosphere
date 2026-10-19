"""Forward then rollback on the Cosmos emulator restores the snapshot (hash compare).

G12: asserts document shape and schema versions only; index behaviour and RU cost are not
exercised by the vNext emulator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from neurosphere_core.migrations import snapshot_hash

if TYPE_CHECKING:
    from .support import Env

pytestmark = pytest.mark.integration


async def test_dry_run_then_forward_then_rollback(env: Env) -> None:
    before = snapshot_hash(await env.documents())
    runner = env.runner("it")

    plan = await runner.plan()
    assert [s.affected_documents for s in plan.steps] == [8, 8]
    assert snapshot_hash(await env.documents()) == before  # dry run wrote nothing

    result = await runner.migrate()
    assert result.documents_written == 16
    migrated = await env.documents()
    assert all(
        d["schema_version"] == 2 and "label" in d and "legacy_label" not in d for d in migrated
    )

    await runner.rollback(0)
    assert snapshot_hash(await env.documents()) == before


async def test_ledger_records_applied_versions(env: Env) -> None:
    from neurosphere_core.migrations import MigrationTarget, ledger_id
    from neurosphere_core.migrations.cosmos import CosmosLedgerStore

    await env.runner("it").migrate()
    ledger = await CosmosLedgerStore(env.ledgers).read(
        ledger_id(MigrationTarget.COSMOS_DOCUMENTS, env.name)
    )
    assert ledger is not None
    assert ledger.current_version == 2
    assert [a.version for a in ledger.applied] == [1, 2]
    assert ledger.lease is None
    assert ledger.etag
