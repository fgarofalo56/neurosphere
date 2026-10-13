"""Hash chain: contract agreement, end-to-end verification, tamper detection, no forks."""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.audit import (
    AuditDraft,
    AuditRepository,
    InMemoryAuditStore,
    TailPointer,
    build_before,
    compute_record_hash,
    digests_equal,
    seal,
    verify_chain,
)
from neurosphere_core.audit import canonical as canonical_module
from neurosphere_core.audit.store import StoredTail
from neurosphere_core.errors import DependencyTransientError

from .audit_helpers import CHAIN, StepClock, make_ctx, make_repo, mixed_drafts, subject

_EXAMPLES = (
    Path(__file__).resolve().parents[4] / "packages/contracts/schemas/audit/v1/examples/valid"
)
N = 24


def _contract_examples() -> list[dict[str, Any]]:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_EXAMPLES.glob("*.json"))]
    return sorted(docs, key=lambda d: d["sequence"])


async def _filled(n: int = N) -> tuple[AuditRepository, InMemoryAuditStore]:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    for draft in mixed_drafts(n):
        await repo.append(CHAIN, draft)
    return repo, store


def _sorted_docs(store: InMemoryAuditStore) -> list[dict[str, Any]]:
    return sorted(store.raw_documents(CHAIN), key=lambda d: d["sequence"])


# -- agreement with the PRP-01 contract ------------------------------------------------------


def test_record_hash_matches_contract_examples() -> None:
    docs = _contract_examples()
    assert len(docs) == 3
    for doc in docs:
        assert digests_equal(compute_record_hash(doc), doc["record_hash"])


def test_contract_example_chain_verifies() -> None:
    result = verify_chain(_contract_examples(), chain_id="contoso.domain-retail")
    assert result.ok, result
    assert result.records_checked == 3


def test_sealed_record_reproduces_contract_example_hash() -> None:
    head = _contract_examples()[0]
    draft_fields = {
        k: head[k]
        for k in (
            "kind",
            "actor",
            "scope_hash",
            "correlation_id",
            "operation",
            "channel",
            "intent_id",
            "subject",
            "outcome",
            "denial",
        )
    }
    draft = AuditDraft.model_validate(draft_fields)
    record = seal(
        draft,
        chain_id=head["chain_id"],
        sequence=0,
        previous_hash=None,
        audit_id=head["audit_id"],
        recorded_at=datetime(2026, 10, 10, 17, 5, 20, tzinfo=UTC),
    )
    # recorded_at precision differs from the example (microseconds), so compare the structure.
    doc = record.model_dump(mode="json")
    assert set(doc) == set(head)
    assert digests_equal(compute_record_hash(doc), record.record_hash.root)


# -- end-to-end chain ------------------------------------------------------------------------


async def test_chain_links_and_verifies_end_to_end() -> None:
    repo, _ = await _filled()
    records = await repo.read_range(CHAIN, start=0, limit=500)
    assert [r.sequence for r in records] == list(range(N))
    assert records[0].previous_hash is None
    for prev, cur in itertools.pairwise(records):
        assert cur.previous_hash is not None
        assert digests_equal(cur.previous_hash.root, prev.record_hash.root)
    result = await repo.verify(CHAIN)
    assert result.ok and result.records_checked == N and result.first_invalid_index is None


async def test_empty_chain_verifies() -> None:
    result = await make_repo().verify(CHAIN)
    assert result.ok and result.records_checked == 0


async def test_partial_range_verifies_with_anchor() -> None:
    repo, _ = await _filled()
    records = await repo.read_range(CHAIN, start=10, limit=5)
    anchor = (await repo.read_range(CHAIN, start=9, limit=1))[0].record_hash.root
    assert verify_chain(records, chain_id=CHAIN, start_sequence=10, anchor_hash=anchor).ok
    bad = verify_chain(records, chain_id=CHAIN, start_sequence=10, anchor_hash=None)
    assert (bad.ok, bad.first_invalid_index, bad.reason) == (False, 0, "previous_hash_mismatch")


async def test_comparisons_use_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = await _filled(4)
    calls: list[int] = []
    real = canonical_module.hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(canonical_module.hmac, "compare_digest", spy)
    assert (await repo.verify(CHAIN)).ok
    assert len(calls) >= 4


# -- tamper detection --------------------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 7, N - 1])
async def test_altered_record_detected_at_its_index(index: int) -> None:
    repo, store = await _filled()
    doc = _sorted_docs(store)[index]
    doc["correlation_id"] = "corr-forged"
    store.simulate_overwrite(CHAIN, index, doc)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        index,
        "record_hash_mismatch",
    )


@pytest.mark.parametrize("index", [0, 7, N - 2])
async def test_altered_and_rehashed_record_breaks_the_next_link(index: int) -> None:
    repo, store = await _filled()
    doc = _sorted_docs(store)[index]
    doc["operation"] = "graph.query"
    doc["record_hash"] = compute_record_hash(doc)
    store.simulate_overwrite(CHAIN, index, doc)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        index + 1,
        "previous_hash_mismatch",
    )


async def test_rehashed_last_record_detected_by_tail_anchor() -> None:
    repo, store = await _filled()
    doc = _sorted_docs(store)[-1]
    doc["operation"] = "graph.query"
    doc["record_hash"] = compute_record_hash(doc)
    store.simulate_overwrite(CHAIN, N - 1, doc)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (False, N, "tail_mismatch")


@pytest.mark.parametrize("index", [0, 7, N - 2])
async def test_removed_record_detected_at_its_position(index: int) -> None:
    repo, store = await _filled()
    store.simulate_remove(CHAIN, index)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        index,
        "sequence_mismatch",
    )


async def test_removed_tail_record_detected_by_tail_anchor() -> None:
    repo, store = await _filled()
    store.simulate_remove(CHAIN, N - 1)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        N - 1,
        "tail_mismatch",
    )


@pytest.mark.parametrize("index", [0, 7, N - 2])
async def test_reordered_records_detected_at_first_displaced_index(index: int) -> None:
    repo, _ = await _filled()
    records = await repo.read_range(CHAIN, start=0, limit=500)
    records[index], records[index + 1] = records[index + 1], records[index]
    result = verify_chain(records, chain_id=CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        index,
        "sequence_mismatch",
    )


async def test_reordering_by_rewriting_sequence_numbers_is_detected() -> None:
    repo, store = await _filled()
    docs = _sorted_docs(store)
    a, b = docs[5], docs[6]
    a["sequence"], b["sequence"] = 6, 5
    store.simulate_overwrite(CHAIN, 5, b)
    store.simulate_overwrite(CHAIN, 6, a)
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index) == (False, 5)
    assert result.reason == "record_hash_mismatch"


async def test_injected_fork_is_detected() -> None:
    repo, store = await _filled()
    docs = _sorted_docs(store)
    fork = seal(
        build_before(make_ctx(), subject("etag-fork")),
        chain_id=CHAIN,
        sequence=10,
        previous_hash=docs[9]["record_hash"],
        audit_id="99999999-0000-4000-8000-000000000000",
        recorded_at=StepClock()(),
    )
    store.simulate_insert(CHAIN, "rec-fork", fork.model_dump(mode="json"))
    result = await repo.verify(CHAIN)
    assert (result.ok, result.first_invalid_index, result.reason) == (
        False,
        11,
        "sequence_mismatch",
    )


def test_wrong_chain_and_invalid_documents_are_reported() -> None:
    store_docs = asyncio.run(_filled(3))[1].raw_documents(CHAIN)
    docs = sorted(store_docs, key=lambda d: d["sequence"])
    assert verify_chain(docs, chain_id="other.chain").reason == "chain_id_mismatch"
    broken = [*docs[:1], {**docs[1], "kind": "erased"}, *docs[2:]]
    result = verify_chain(broken, chain_id=CHAIN)
    assert (result.first_invalid_index, result.reason) == (1, "invalid_record")


def test_tail_pointer_for_other_chain_is_a_mismatch() -> None:
    docs = sorted(asyncio.run(_filled(2))[1].raw_documents(CHAIN), key=lambda d: d["sequence"])
    tail = TailPointer(chain_id="x", sequence=1, record_hash=docs[1]["record_hash"])
    assert verify_chain(docs, chain_id=CHAIN, tail=tail).reason == "tail_mismatch"


# -- concurrency: parallel writers never fork the chain -----------------------------------------


async def test_parallel_writers_on_one_partition_never_fork() -> None:
    store = InMemoryAuditStore()
    writers = [AuditRepository(store, clock=StepClock()) for _ in range(20)]
    per_writer = 5

    async def write(repo: AuditRepository) -> list[int]:
        return [(await repo.append(CHAIN, d)).sequence for d in mixed_drafts(per_writer)]

    results = await asyncio.gather(*(write(w) for w in writers))
    sequences = sorted(s for batch in results for s in batch)
    total = len(writers) * per_writer
    assert sequences == list(range(total))  # unique and contiguous: no fork, no gap
    assert store.sequence_conflicts > 0  # writers really raced for the same sequence
    verification = await writers[0].verify(CHAIN)
    assert verification.ok and verification.records_checked == total
    audit_ids = {d["audit_id"] for d in store.raw_documents(CHAIN)}
    assert len(audit_ids) == total


async def test_parallel_appends_through_one_repository_never_fork() -> None:
    repo = AuditRepository(InMemoryAuditStore(), clock=StepClock())
    records = await asyncio.gather(*(repo.append(CHAIN, d) for d in mixed_drafts(40)))
    assert sorted(r.sequence for r in records) == list(range(40))
    assert (await repo.verify(CHAIN)).ok


class _TailWriteFailsOnce(InMemoryAuditStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_tail = False

    async def write_tail(self, tail: TailPointer, *, if_match: str | None) -> None:
        if self.fail_next_tail:
            self.fail_next_tail = False
            raise ConnectionError("tail write lost")
        await super().write_tail(tail, if_match=if_match)


async def test_lagging_tail_after_crash_is_repaired_without_fork() -> None:
    store = _TailWriteFailsOnce()
    repo = make_repo(store)
    drafts = mixed_drafts(6)
    for draft in drafts[:3]:
        await repo.append(CHAIN, draft)
    store.fail_next_tail = True
    with pytest.raises(DependencyTransientError) as info:
        await repo.append(CHAIN, drafts[3])  # record 3 is durable, tail still points at 2
    assert info.value.reason == "audit_write_failed"
    tail = await store.read_tail(CHAIN)
    assert isinstance(tail, StoredTail) and tail.tail.sequence == 2
    for draft in drafts[4:]:
        await repo.append(CHAIN, draft)
    result = await repo.verify(CHAIN)
    assert result.ok and result.records_checked == 6


async def test_record_that_does_not_link_blocks_further_appends() -> None:
    repo, store = await _filled(3)
    bogus = seal(
        build_before(make_ctx(), subject()),
        chain_id=CHAIN,
        sequence=3,
        previous_hash="sha256:" + "0" * 64,
        audit_id="99999999-0000-4000-8000-000000000001",
        recorded_at=StepClock()(),
    )
    store.simulate_overwrite(CHAIN, 3, bogus.model_dump(mode="json"))
    with pytest.raises(DependencyTransientError) as info:
        await repo.append(CHAIN, mixed_drafts(1)[0])
    assert info.value.reason == "audit_chain_broken"


async def test_verify_refuses_to_walk_a_tail_that_claims_more_than_the_limit() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    for draft in mixed_drafts(3):
        await repo.append(CHAIN, draft)
    assert (await repo.verify(CHAIN)).ok

    limited = await repo.verify(CHAIN, max_records=2)
    assert not limited.ok
    assert limited.reason == "verify_limit_exceeded"
    assert limited.records_checked == 0


async def test_verify_with_forged_huge_tail_returns_instead_of_paging_forever() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    for draft in mixed_drafts(3):
        await repo.append(CHAIN, draft)
    current = await store.read_tail(CHAIN)
    assert current is not None
    forged = current.tail.model_copy(update={"sequence": 10**12})
    await store.write_tail(forged, if_match=current.etag)

    result = await asyncio.wait_for(repo.verify(CHAIN), timeout=5)
    assert not result.ok
    assert result.reason == "verify_limit_exceeded"
