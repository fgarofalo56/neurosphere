"""Replaying the same quarantined event twice produces one ledger effect."""

from __future__ import annotations

import asyncio

from neurosphere_workers.ingestion.models import compute_doc_id

from .support import T0, Doc, FakeBlobContainer, Harness, quarantine_poison, run_cli, telemetry_at


def _seed(container: FakeBlobContainer, harness: Harness, template: Doc, event_id: str) -> str:
    doc = telemetry_at(template, event_id, T0)
    asyncio.run(quarantine_poison(container, harness, doc))
    return compute_doc_id(doc["customer_id"], doc["source_id"], event_id)


def test_second_replay_reports_already_replayed_and_changes_nothing(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    doc_id = _seed(container, harness, template, "evt-r1")
    assert not harness.ledger.effects  # poison: nothing accepted yet

    first = run_cli(["replay", "--id", doc_id], container, harness)
    assert first.code == 0, first.err
    assert "replayed" in first.out
    assert list(harness.ledger.effects) == [doc_id]
    assert harness.ledger.write_calls == 1
    assert container.names("replayed/") == [f"replayed/{doc_id}.json"]
    blobs_after_first = dict(container.blobs)

    second = run_cli(["replay", "--id", doc_id], container, harness)

    assert second.code == 0
    assert "already replayed" in second.out
    assert harness.ledger.write_calls == 1  # one ledger effect, no second call
    assert harness.archive.write_calls == 1 + 3  # 3 poisoned attempts + the one replay
    assert container.blobs == blobs_after_first


def test_without_replay_marker_the_accepted_marker_still_prevents_a_second_effect(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    doc_id = _seed(container, harness, template, "evt-r2")
    assert run_cli(["replay", "--id", doc_id], container, harness).code == 0
    del container.blobs[f"replayed/{doc_id}.json"]  # simulate a lost marker (crash window)

    again = run_cli(["replay", "--id", doc_id], container, harness)

    assert again.code == 0, again.err
    assert "duplicate" in again.out
    assert harness.ledger.write_calls == 1
    assert len(harness.ledger.effects) == 1


def test_failed_replay_writes_no_marker(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    doc_id = _seed(container, harness, template, "evt-r3")
    harness.ledger.fail_for(doc_id)  # still poison on replay: quarantined again

    run = run_cli(["replay", "--id", doc_id], container, harness)

    assert run.code == 1
    assert not container.names("replayed/")
    assert not harness.markers.marked
