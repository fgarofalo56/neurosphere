"""Role factories wire the resolving sources (PRP-137 item 6)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_workers.agent_identity import ResolvingRecordSource, ResolvingTraceEventSource
from neurosphere_workers.agent_identity.wiring import CountersRole
from neurosphere_workers.projections.outbox import SINK_AGGREGATES
from neurosphere_workers.runtime import factories

from .fakes import CUSTOMER, doc, loaded
from .wiring_support import (
    WORKER_SCOPE,
    RecordingProjection,
    Rig,
    TickHolder,
    config,
    entry,
    install,
)

ALIAS_TARGET = f"commercial:{CUSTOMER}:foundry:agent:aliased"


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    return install(monkeypatch)


def _tick(role: Any) -> Any:
    assert isinstance(role, CountersRole)
    inner = role._inner
    assert isinstance(inner, TickHolder)
    return inner.tick


async def test_projections_and_aggregates_get_resolving_sources(rig: Rig) -> None:
    async with ClientLifetime() as lifetime:
        await factories.build_projections(config(), lifetime)
        await factories.build_aggregates(config(), lifetime)
    catalog, aggregates = RecordingProjection.instances
    assert isinstance(catalog.kwargs["source"], ResolvingTraceEventSource)
    assert isinstance(aggregates.kwargs["events"], ResolvingTraceEventSource)
    # one resolver per role, not one shared by both
    assert catalog.source._resolver is not aggregates.source._resolver


async def test_evaluation_gets_a_resolving_record_source(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[ResolvingRecordSource] = []

    class Capture(ResolvingRecordSource):
        def __init__(self, inner: Any, resolver: Any) -> None:
            super().__init__(inner, resolver)
            seen.append(self)

    async def no_settings(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(setting=lambda _name: None)

    monkeypatch.setenv("NS_WORKER_EVAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(factories, "ResolvingRecordSource", Capture)
    monkeypatch.setattr(
        factories,
        "CosmosAdminConfigRepository",
        SimpleNamespace(from_client=lambda *a, **k: object()),
    )
    monkeypatch.setattr(factories, "load_stored_settings", no_settings)
    monkeypatch.setattr(factories, "create_cosmos_client", lambda *_a, **_k: object())
    monkeypatch.setattr(
        factories, "_evaluation_registry", lambda *_a: (object(), object(), object())
    )
    monkeypatch.setattr(factories, "_evaluation_judge", lambda *_a, **_k: object())
    monkeypatch.setattr(factories, "_pilot_datasets", lambda *_a: [])
    monkeypatch.setattr(factories, "ArchiveRecordSource", lambda _reader, _customer: object())
    monkeypatch.setattr(
        factories, "CosmosEvaluationStore", SimpleNamespace(from_client=lambda *a, **k: object())
    )
    async with ClientLifetime() as lifetime:
        role = await factories.build_evaluation(config(), lifetime)
    assert isinstance(role, CountersRole)
    assert len(seen) == 1
    assert role.counters()["derived"] == 0


async def test_lookup_outage_retries_the_entry_without_advancing(rig: Rig) -> None:
    rig.inner.add(loaded("d1", doc("e1")))
    await rig.outbox.append(entry("d1"))
    async with ClientLifetime() as lifetime:
        role = await factories.build_aggregates(config(), lifetime)
    tick = _tick(role)
    projection = RecordingProjection.instances[0]

    rig.repo.error = RuntimeError("catalog down")
    await tick()
    assert await rig.checkpoints.get(SINK_AGGREGATES, CUSTOMER) is None
    assert projection.seen == []  # nothing was filed under a derived-id series

    rig.repo.error = None
    rig.repo.values["ext-1"] = ALIAS_TARGET
    await tick()
    assert await rig.checkpoints.get(SINK_AGGREGATES, CUSTOMER) is not None
    (event,) = projection.seen
    assert event is not None and event.event.canonical_agent_id is not None
    assert event.event.canonical_agent_id.root == ALIAS_TARGET
    assert isinstance(role, CountersRole)
    assert role.counters()["lookup_failures"] == 1


async def test_lookup_scope_is_the_workers_not_the_events(rig: Rig) -> None:
    # The event claims another customer's identity; the lookup still runs in the worker's scope.
    rig.inner.add(loaded("d1", doc("e1", domain_id="commercial:synthco:sandbox:domain:other")))
    async with ClientLifetime() as lifetime:
        await factories.build_aggregates(config(), lifetime)
    projection = RecordingProjection.instances[0]
    await projection.handle(entry("d1"))
    assert rig.repo.scopes_seen == [WORKER_SCOPE]
    assert rig.scopes.gets >= 1


async def test_status_counters_are_names_and_integers_only(rig: Rig) -> None:
    rig.inner.add(loaded("d1", doc("e1")))
    async with ClientLifetime() as lifetime:
        role = await factories.build_projections(config(), lifetime)
    projection = RecordingProjection.instances[0]
    await projection.handle(entry("d1"))
    counters = role.counters()  # type: ignore[attr-defined]
    assert counters["derived"] == 1
    for name in (
        "resolved_alias",
        "lookup_failures",
        "agent_drafts_created",
        "agent_drafts_existing",
        "agent_draft_out_of_scope",
    ):
        assert counters[name] == 0
    assert all(isinstance(v, int) for v in counters.values())
    assert ALIAS_TARGET not in repr(counters)
