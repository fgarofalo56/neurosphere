"""PRP-43 item 1: id collisions are quarantined; other create failures hold the checkpoint."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from neurosphere_core.catalog.repo.engine import ENTITY_ID_TAKEN_REASON
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_workers.projections.catalog import InMemoryCandidateQuarantine

from .catalog_support import Doc, Rig, domains_of, trace_with_delegation


@pytest.fixture
def docs() -> list[Doc]:
    return trace_with_delegation()


def _raising(exc: Exception) -> Any:
    async def create_entity(*_args: object, **_kwargs: object) -> object:
        raise exc

    return create_entity


async def test_collision_is_quarantined_and_checkpoint_advances(docs: list[Doc]) -> None:
    rig = Rig(docs, domains_of(docs))
    rig.repo.create_entity = _raising(  # type: ignore[method-assign]
        InvalidSchemaError("taken", reason=ENTITY_ID_TAKEN_REASON)
    )
    await rig.fill_outbox()
    result = await rig.drain()
    assert result.ok and result.delivered == len(docs)
    stats = rig.projection.stats
    assert stats.skipped_collision > 0
    assert rig.repo.puts == 0
    quarantine = rig.projection.quarantine
    assert isinstance(quarantine, InMemoryCandidateQuarantine)
    assert quarantine.records
    assert {r.reason for r in quarantine.records.values()} == {"entity_id_collision"}


async def test_forbidden_create_propagates_and_holds_checkpoint(docs: list[Doc]) -> None:
    rig = Rig(docs, domains_of(docs))
    rig.repo.create_entity = _raising(ForbiddenError("no"))  # type: ignore[method-assign]
    await rig.fill_outbox()
    result = await rig.drain()
    assert not result.ok
    assert rig.projection.stats.skipped_collision == 0


async def test_other_schema_failure_propagates(docs: list[Doc]) -> None:
    rig = Rig(docs, domains_of(docs))
    rig.repo.create_entity = _raising(InvalidSchemaError("bad"))  # type: ignore[method-assign]
    await rig.fill_outbox()
    result = await rig.drain()
    assert not result.ok


async def test_replay_of_quarantined_candidate_leaves_one_record(docs: list[Doc]) -> None:
    rig = Rig(docs, ["commercial:synthco:sandbox:domain:not-in-this-trace"])
    await rig.fill_outbox()
    await rig.drain()
    quarantine = rig.projection.quarantine
    assert isinstance(quarantine, InMemoryCandidateQuarantine)
    first = dict(quarantine.records)
    rig.checkpoints._cursors.clear()
    await rig.drain()
    assert set(quarantine.records) == set(first)


async def test_threshold_warns_once_with_counts_only(
    docs: list[Doc], caplog: pytest.LogCaptureFixture
) -> None:
    rig = Rig(docs, ["commercial:synthco:sandbox:domain:not-in-this-trace"])
    rig.projection._warn_at = 1
    await rig.fill_outbox()
    with caplog.at_level(logging.WARNING):
        await rig.drain()
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "quarantined" in r.message
    ]
    assert len(warnings) == 1
    for record in rig.projection.quarantine.records.values():  # type: ignore[attr-defined]
        assert record.id not in warnings[0].getMessage()
