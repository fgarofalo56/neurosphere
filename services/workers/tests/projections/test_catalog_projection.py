"""Catalog projection (PRP-10 item 3): edges from sandbox traces, replay, checkpoints, locks."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.catalog import present_edge
from neurosphere_core.catalog.protocol import CatalogEdge
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    StaleVersionError,
)
from neurosphere_core.paging import PageRequest
from neurosphere_workers.projections.catalog import (
    CONFIDENCE_DELEGATION,
    INFERENCE_VERSION,
    AliasModelResolver,
    CatalogProjection,
    WorkloadScopeProvider,
    delegation_candidate,
    deterministic_model_id,
)
from neurosphere_workers.projections.catalog import (
    scope as scope_module,
)
from neurosphere_workers.projections.outbox import OutboxEntry, OutboxReader
from neurosphere_workers.projections.outbox.models import ledger_change_outbox_id

from .catalog_support import (
    AUDITOR_OBJECT_ID,
    NOW,
    Doc,
    Rig,
    StaticClaims,
    build_deriver,
    domains_of,
    loaded,
    lock_override,
    make_claims,
    outbox_entry,
    trace_with_delegation,
)


@pytest.fixture
def docs() -> list[Doc]:
    return trace_with_delegation()


@pytest.fixture
def rig(docs: list[Doc]) -> Rig:
    return Rig(docs, domains_of(docs))


async def snapshot(rig: Rig, *, etags: bool = True) -> dict[str, tuple[Any, ...]]:
    scope = await rig.worker_scope()
    out: dict[str, tuple[Any, ...]] = {}
    for edge_id in dict.fromkeys(rig.repo.put_ids):
        edge = await rig.inner.get_edge(scope, edge_id)
        assert edge is not None
        out[edge_id] = (
            edge.version.root,
            edge.etag.root if etags else "",
            tuple(e.root for e in edge.evidence_ids),
            float(edge.confidence),
        )
    return out


async def observations(rig: Rig, edge_id: str) -> list[Any]:
    scope = await rig.auditor_scope()
    page = await rig.inner.list_observations(scope, edge_id, PageRequest(page_size=500))
    return list(page.items)


async def stored_edges(rig: Rig) -> list[CatalogEdge]:
    scope = await rig.worker_scope()
    found = [await rig.inner.get_edge(scope, i) for i in dict.fromkeys(rig.repo.put_ids)]
    return [e for e in found if e is not None]


# ---------------------------------------------------------------- acceptance: edges from a trace


async def test_sandbox_trace_produces_invokes_and_uses_model_edges(rig: Rig) -> None:
    await rig.fill_outbox()
    result = await rig.drain()
    assert result.ok and result.delivered == len(rig.docs)

    edges = await stored_edges(rig)
    kinds = {(e.relation_type, e.target_id.split(":")[3]) for e in edges}
    assert ("invokes", "agent") in kinds  # delegation
    assert ("invokes", "tool") in kinds  # tool_call
    assert ("uses_model", "model_deployment") in kinds  # model_call

    doc_ids = {item.doc_id for item in rig.items}
    for edge in edges:
        assert edge.status.root == "inferred"
        assert edge.provenance.method == "trace_observation"
        assert edge.provenance.inference_version is not None
        assert edge.provenance.inference_version.root == INFERENCE_VERSION
        assert 0.0 < edge.confidence <= 1.0
        assert edge.first_observed.root <= edge.last_observed.root
        assert edge.validity.valid_from.root == edge.first_observed.root
        assert edge.lock.locked is False
        assert edge.evidence_ids, "an inferred edge always carries evidence IDs"
        for evidence in (e.root for e in edge.evidence_ids):
            assert evidence.startswith(("event:", "trace:"))
            if evidence.startswith("event:"):
                assert evidence.removeprefix("event:") in doc_ids  # a pointer to a stored event
        assert edge.security_evidence_ids == []


async def test_delegation_edge_is_corroborated_by_both_spans(rig: Rig) -> None:
    await rig.fill_outbox()
    await rig.drain()
    delegation = [
        e
        for e in await stored_edges(rig)
        if e.relation_type == "invokes" and e.target_id.split(":")[3] == "agent"
    ]
    assert delegation
    for edge in delegation:
        assert edge.confidence == CONFIDENCE_DELEGATION
        events = [e.root for e in edge.evidence_ids if e.root.startswith("event:")]
        assert len(events) >= 2


async def test_evidence_never_embeds_payload_references(docs: list[Doc]) -> None:
    marked = copy.deepcopy(docs)
    for doc in marked:
        doc["payload_ref"] = {"pointer": "blob://secret/body-123", "redaction_state": "redacted"}
    rig = Rig(marked, domains_of(marked))
    await rig.fill_outbox()
    await rig.drain()
    for edge in await stored_edges(rig):
        assert all("body-123" not in e.root for e in edge.evidence_ids)
        assert edge.attributes is None


# ---------------------------------------------------------------- acceptance: idempotent replay


async def test_replaying_the_same_batch_adds_no_edges_or_observations(rig: Rig) -> None:
    await rig.fill_outbox()
    await rig.drain()
    before = await snapshot(rig)
    obs_before = {i: len(await observations(rig, i)) for i in before}
    puts_before = rig.repo.puts
    assert before and all(n >= 1 for n in obs_before.values())

    rig.checkpoints._cursors.clear()
    replay = await rig.drain()

    assert replay.ok and replay.delivered == len(rig.docs)
    assert await snapshot(rig) == before
    assert {i: len(await observations(rig, i)) for i in before} == obs_before
    assert rig.repo.puts == puts_before, "an unchanged edge must not be rewritten"
    assert rig.projection.stats.observations_replayed > 0


# ---------------------------------------------------------------- acceptance: checkpoint safety


async def test_checkpoint_advances_only_after_durable_write(docs: list[Doc]) -> None:
    clean = Rig(docs, domains_of(docs))
    await clean.fill_outbox()
    await clean.drain()
    expected = await snapshot(clean, etags=False)

    rig = Rig(docs, domains_of(docs))
    await rig.fill_outbox()
    rig.repo.fail_after_puts = 2
    crashed = await rig.drain()
    assert not crashed.ok and crashed.error == "DependencyTransientError"
    assert crashed.delivered < len(docs)

    entries = rig.outbox.entries("synthco")
    cursor = await rig.checkpoints.get("catalog", "synthco")
    stored = await rig.outbox.read_after("synthco", None, 1000)
    delivered = [s for s in stored if cursor is not None and s.cursor <= cursor]
    assert len(delivered) == crashed.delivered
    assert len(delivered) < len(entries)
    puts_at_crash = rig.repo.puts
    assert puts_at_crash == 2

    # restart: a fresh reader over the same stores resumes after the checkpoint
    rig.repo.fail_after_puts = None
    rig.reader = OutboxReader(rig.outbox, rig.checkpoints, batch_size=3)
    resumed = await rig.drain()
    assert resumed.ok
    assert resumed.delivered == len(docs) - crashed.delivered
    assert await snapshot(rig, etags=False) == expected


async def test_missing_event_raises_so_the_checkpoint_holds(rig: Rig) -> None:
    await rig.fill_outbox()
    first = rig.items[0]
    rig.source._by_doc.pop((first.event.customer_id.root, first.doc_id))
    result = await rig.drain()
    assert result.error == "DependencyTransientError"
    assert result.delivered == 0
    assert await rig.checkpoints.get("catalog", "synthco") is None


async def test_stale_version_is_retried_a_bounded_number_of_times(rig: Rig) -> None:
    await rig.fill_outbox()
    rig.repo.stale_next_puts = 2  # below the bound (3 attempts)
    assert (await rig.drain()).ok
    assert rig.projection.stats.stale_retries == 2

    wedged = Rig(rig.docs, rig.domains)
    await wedged.fill_outbox()
    wedged.repo.stale_next_puts = 99
    result = await wedged.drain()
    assert result.error == StaleVersionError.__name__
    assert wedged.projection.stats.stale_retries == 3
    assert result.delivered < len(rig.docs)  # the checkpoint stopped before the failing entry
    assert wedged.repo.puts == 0


# ---------------------------------------------------------------- acceptance: locks and conflicts


async def test_reinference_on_a_locked_edge_keeps_presented_state_and_queues_conflict(
    docs: list[Doc],
) -> None:
    model_call = next(
        d for d in docs if d["span_kind"] == "model_call" and d["outcome"] == "success"
    )
    rig = Rig([model_call], domains_of([model_call]))
    await rig.fill_outbox()
    assert (await rig.drain()).ok
    (edge,) = await stored_edges(rig)
    assert edge.relation_type == "uses_model"
    scope = await rig.worker_scope()
    await rig.inner.put_override(
        scope, lock_override(edge, decided_at="2026-10-15T00:00:00Z", confidence=0.1)
    )
    locked_before = await rig.inner.get_edge(scope, edge.id)
    assert locked_before is not None

    again = copy.deepcopy(model_call)  # same agent and model, a later event
    again["event_id"] = "evt-reinference-0001"
    again["span_id"] = "ab" * 8
    again["event_time"] = "2026-10-20T10:00:00.000Z"
    fresh = loaded(again)
    rig.source.add(fresh)
    await rig.outbox.append(outbox_entry(fresh))
    assert (await rig.drain()).ok

    after = await rig.inner.get_edge(scope, edge.id)
    assert after is not None
    overrides = await rig.inner.list_overrides(scope, edge.id)
    presented = present_edge(after, overrides, NOW)
    assert presented.confidence == pytest.approx(0.1)  # presented state follows the lock
    assert presented.pinned and presented.status == "curated"
    assert float(after.confidence) == float(edge.confidence)  # the observed edge is unchanged
    assert {e.root for e in after.evidence_ids} > {e.root for e in edge.evidence_ids}
    assert f"event:{fresh.doc_id}" in {e.root for e in after.evidence_ids}

    seen = await observations(rig, edge.id)
    assert len(seen) == 2  # the original and the re-inference are both retained
    assert any(f"event:{fresh.doc_id}" in o.evidence_ids for o in seen)

    auditor = await rig.auditor_scope()
    queued = await rig.queue.list_open(auditor)
    assert len(queued) == 1
    assert queued[0].reason == "conflicts_with_lock"
    assert queued[0].edge_id == edge.id
    assert f"event:{fresh.doc_id}" in queued[0].new_evidence_ids

    # replaying the re-inference neither duplicates the observation nor the review item
    rig.checkpoints._cursors.clear()
    assert (await rig.drain()).ok
    assert len(await observations(rig, edge.id)) == 2
    assert len(await rig.queue.list_open(auditor)) == 1


# ---------------------------------------------------------------- no-ops and scope


async def test_ledger_changes_and_cost_events_are_acknowledged_without_work(rig: Rig) -> None:
    ledger = OutboxEntry(
        id=ledger_change_outbox_id("entry-1", "hash-1"),
        customer_id="synthco",
        kind="ledger_change",
        ref_id="entry-1",
        entity="ledger_entry",
        content_hash="hash-1",
    )
    cost = outbox_entry(rig.items[0], id="cost-1", event_kind="cost")
    await rig.outbox.append(ledger)
    await rig.outbox.append(cost)
    result = await rig.drain()
    assert result.ok and result.delivered == 2
    assert rig.projection.stats.non_event == 2
    assert rig.source.reads == 0
    assert rig.repo.puts == 0


async def test_events_outside_the_worker_scope_are_skipped_not_written(docs: list[Doc]) -> None:
    other = ["commercial:synthco:sandbox:domain:not-in-this-trace"]
    rig = Rig(docs, other)
    await rig.fill_outbox()
    result = await rig.drain()
    assert result.ok and result.delivered == len(docs)  # the checkpoint is not wedged
    assert rig.projection.stats.skipped_out_of_scope > 0
    assert rig.repo.puts == 0


async def test_entry_for_another_customer_is_refused(rig: Rig) -> None:
    foreign = outbox_entry(rig.items[0], customer_id="othercorp")
    with pytest.raises(ForbiddenError):
        await rig.projection.handle(foreign)


async def test_worker_scope_comes_from_the_deriver_for_a_workload_identity(
    docs: list[Doc],
) -> None:
    domains = domains_of(docs)
    deriver = build_deriver(domains)
    provider = WorkloadScopeProvider(deriver, StaticClaims(make_claims(AUDITOR_OBJECT_ID, "user")))
    with pytest.raises(ForbiddenError):  # a user token never runs the projection
        await provider.get()

    claims = StaticClaims(make_claims("6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"))
    worker = WorkloadScopeProvider(deriver, claims)
    scope = await worker.get()
    assert set(scope.allowed_domains) == set(domains)
    assert scope.customer_id == "synthco"
    assert await worker.get() is scope
    assert claims.calls == 1  # cached until shortly before expiry

    unknown = WorkloadScopeProvider(deriver, StaticClaims(make_claims(AUDITOR_OBJECT_ID)))
    assert (await unknown.get()).allowed_domains == ()  # no policy means no domains (deny)


def test_worker_never_builds_a_scope_directly() -> None:
    package = Path(scope_module.__file__).parent
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
            assert name != "_from_verified_contract", path.name
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "IdentityScope":
                pytest.fail(f"{path.name} constructs IdentityScope directly")


# ---------------------------------------------------------------- mapping and resolvers


def test_delegation_requires_matching_trace_parent_and_distinct_agents(docs: list[Doc]) -> None:
    by_id = {d["span_id"]: d for d in docs}
    run = next(
        d
        for d in docs
        if d["span_kind"] == "agent_run"
        and d.get("parent_span_id") in by_id
        and by_id[d["parent_span_id"]]["span_kind"] == "delegation"
    )
    parent = loaded(by_id[run["parent_span_id"]])
    child = loaded(run)
    candidate = delegation_candidate(parent, child)
    assert candidate is not None
    assert candidate.source_id == by_id[run["parent_span_id"]]["canonical_agent_id"]
    assert candidate.target_id == run["canonical_agent_id"]

    other_trace = copy.deepcopy(run)
    other_trace["trace_id"] = "f" * 32
    assert delegation_candidate(parent, loaded(other_trace)) is None
    same_agent = copy.deepcopy(run)
    same_agent["canonical_agent_id"] = by_id[run["parent_span_id"]]["canonical_agent_id"]
    assert delegation_candidate(parent, loaded(same_agent)) is None
    assert delegation_candidate(child, parent) is None  # wrong span kinds


async def test_alias_resolver_prefers_the_curated_deployment_id(docs: list[Doc]) -> None:
    model_call = loaded(next(d for d in docs if d["span_kind"] == "model_call"))
    curated = "commercial:synthco:sandbox:model_deployment:gpt-large"

    class _Repo:
        def __init__(self, answer: str | None) -> None:
            self.answer = answer
            self.keys: list[Any] = []

        async def resolve_alias(self, scope: Any, key: Any) -> str | None:
            self.keys.append(key)
            return self.answer

    scope = await Rig(docs, domains_of(docs)).worker_scope()
    hit = AliasModelResolver(_Repo(curated))  # type: ignore[arg-type]
    assert await hit.resolve(scope, model_call.event) == curated
    miss = AliasModelResolver(_Repo(None))  # type: ignore[arg-type]
    assert await miss.resolve(scope, model_call.event) == deterministic_model_id(model_call.event)


def test_projection_requires_at_least_one_attempt(rig: Rig) -> None:
    with pytest.raises(ValueError, match="max_stale_retries"):
        CatalogProjection(
            repository=rig.repo,  # type: ignore[arg-type]
            review_queue=rig.queue,
            source=rig.source,
            scope_provider=rig.projection._scopes,
            max_stale_retries=0,
        )


async def test_transient_repo_errors_are_not_swallowed(rig: Rig) -> None:
    await rig.fill_outbox()
    rig.repo.fail_after_puts = 0
    with pytest.raises(DependencyTransientError):
        for item in rig.items:
            await rig.projection.handle(outbox_entry(item))
