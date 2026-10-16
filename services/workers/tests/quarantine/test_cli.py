"""CLI behaviour against an in-memory container: list, inspect, replay, dry-run, refusals."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from neurosphere_workers.ingestion.models import QuarantineRecord, compute_doc_id
from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.quarantine import BlobQuarantineSink

from .support import T0, Doc, FakeBlobContainer, Harness, quarantine_poison, run_cli, telemetry_at


def _poison(container: FakeBlobContainer, harness: Harness, template: Doc, event_id: str) -> str:
    doc = telemetry_at(template, event_id, T0)
    asyncio.run(quarantine_poison(container, harness, doc))
    return compute_doc_id(doc["customer_id"], doc["source_id"], event_id)


def _put(container: FakeBlobContainer, **fields: object) -> QuarantineRecord:
    base: dict[str, object] = {
        "doc_id": "a" * 64,
        "reason": QuarantineReason.INVALID_SCHEMA,
        "attempts": 1,
        "partition_id": "0",
        "offset": "9",
        "sequence_number": 9,
        "enqueued_time": T0,
        "quarantined_at": datetime(2026, 10, 2, tzinfo=UTC),
        "customer_id": "cust-x",
        "payload": {"customer_id": "cust-x", "note": "synthetic"},
    }
    base.update(fields)
    record = QuarantineRecord.model_validate(base)
    asyncio.run(BlobQuarantineSink(container).write(record))
    return record


def test_list_filters_by_reason_customer_and_date(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    poison_id = _poison(container, harness, template, "evt-l1")
    _put(container)

    everything = run_cli(["list"], container)
    assert everything.code == 0
    assert "2 record(s)" in everything.out

    by_reason = run_cli(["list", "--reason", "retry_budget_exhausted"], container)
    assert poison_id in by_reason.out and "1 record(s)" in by_reason.out

    by_customer = run_cli(["list", "--customer", "cust-x"], container)
    assert "a" * 64 in by_customer.out and "1 record(s)" in by_customer.out

    by_date = run_cli(["list", "--date", "2026-10-02"], container)
    assert "a" * 64 in by_date.out and "1 record(s)" in by_date.out
    assert "0 record(s)" in run_cli(["list", "--date", "2020-01-01"], container).out


def test_inspect_prints_metadata_and_payload(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    doc_id = _poison(container, harness, template, "evt-i1")

    run = run_cli(["inspect", doc_id], container)

    assert run.code == 0
    shown = json.loads(run.out)
    assert shown["reason"] == "retry_budget_exhausted"
    assert shown["attempts"] == 3
    assert shown["replayed"] is False
    assert shown["payload"]["event_id"] == "evt-i1"


def test_inspect_unknown_id_fails(container: FakeBlobContainer) -> None:
    run = run_cli(["inspect", "f" * 64], container)
    assert run.code == 1 and "not found" in run.err


def test_inspect_refuses_a_tampered_blob_with_body_fields(container: FakeBlobContainer) -> None:
    record = _put(container)
    tampered = json.loads(record.model_dump_json())
    tampered["payload"]["prompt"] = "synthetic prompt text"
    container.blobs[f"records/{record.doc_id}.json"] = json.dumps(tampered).encode()

    run = run_cli(["inspect", record.doc_id], container)

    assert run.code == 1
    assert "synthetic prompt text" not in run.out + run.err


def test_dry_run_writes_nothing_anywhere(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    doc_id = _poison(container, harness, template, "evt-d1")
    before = dict(container.blobs)
    uploads = container.upload_calls
    ledger_calls = harness.ledger.write_calls

    run = run_cli(["replay", "--id", doc_id, "--dry-run"], container, harness)

    assert run.code == 0, run.err
    assert "dry-run ok" in run.out
    assert container.blobs == before and container.upload_calls == uploads
    assert harness.ledger.write_calls == ledger_calls
    assert not harness.ledger.effects and not harness.markers.marked
    assert not container.names("replayed/")


def test_dry_run_reports_a_record_the_pipeline_would_reject(
    container: FakeBlobContainer,
) -> None:
    record = _put(container)  # not a valid HubMessage

    run = run_cli(["replay", "--id", record.doc_id, "--dry-run"], container)

    assert run.code == 1
    assert "invalid_wire" in run.err


def test_replay_refuses_a_record_failing_the_redaction_check(
    harness: Harness, container: FakeBlobContainer
) -> None:
    record = _put(container)
    tampered = json.loads(record.model_dump_json())
    tampered["payload"]["response"] = "synthetic response text"
    container.blobs[f"records/{record.doc_id}.json"] = json.dumps(tampered).encode()

    run = run_cli(["replay", "--id", record.doc_id], container, harness)

    assert run.code == 1
    assert "redaction check failed" in run.err
    assert not harness.ledger.write_calls and not harness.archive.write_calls
    assert not container.names("replayed/")


def test_unparseable_record_is_not_replayable(container: FakeBlobContainer) -> None:
    record = _put(
        container,
        doc_id="b" * 64,
        reason=QuarantineReason.INVALID_WIRE,
        payload=None,
        payload_sha256="0" * 64,
        payload_bytes=5,
    )

    run = run_cli(["replay", "--id", record.doc_id], container)

    assert run.code == 1 and "not replayable" in run.err


def test_replay_by_filter_replays_each_match(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    a = _poison(container, harness, template, "evt-f1")
    harness.archive.fail_transient(0)
    b = _poison(container, harness, template, "evt-f2")

    run = run_cli(["replay", "--reason", "retry_budget_exhausted"], container, harness)

    assert run.code == 0, run.err
    assert "2 record(s) match" in run.out
    assert set(harness.ledger.effects) == {a, b}


def test_usage_errors_exit_2(container: FakeBlobContainer) -> None:
    assert run_cli([], container).code == 2
    assert run_cli(["replay"], container).code == 2
    assert run_cli(["list", "--reason", "nope"], container).code == 2
    assert run_cli(["list", "--date", "yesterday"], container).code == 2
    assert run_cli(["bogus"], container).code == 2


def test_unbuildable_sinks_fail_closed_with_exit_1(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    from contextlib import asynccontextmanager

    from .support import load_cli

    doc_id = _poison(container, harness, template, "evt-u1")
    cli = load_cli()

    @asynccontextmanager
    async def unwired():  # type: ignore[no-untyped-def]
        # Wiring (ingestion.wiring) refuses to build when infrastructure is missing.
        from neurosphere_core.errors import InvalidSchemaError

        raise InvalidSchemaError("sinks cannot be built", reason="config")
        yield None

    from io import StringIO

    from .support import container_factory

    err = StringIO()
    code = cli.main(
        ["replay", "--id", doc_id],
        container_factory=container_factory(container),
        deps_factory=unwired,
        out=StringIO(),
        err=err,
    )
    assert code == 1
    assert not container.names("replayed/")
