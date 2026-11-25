"""PRP-103 criterion 7: with capture ON (and OFF) every guard still keeps bodies out.

Each test runs the same scenario twice (``guard_helpers.run_scenario``): an approved active
capture policy with the stored setting on, and the same adapter attached with it off. The
scenario sends one item that is captured, one whose key wrap fails (an index-only drop) and one
OTLP span, each with ``NSCANARY-`` canaries and a credential-shaped value in its body fields.
"""

from __future__ import annotations

import copy
import gzip
import json
import secrets
from pathlib import Path

import pytest
from neurosphere_core.audit import verify_chain
from neurosphere_core.audit.content_guard import assert_metadata_only
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.payload import find_body_fields
from neurosphere_workers.archive.serialize import build_blob, redact_record
from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.quarantine import BlobQuarantineSink

from . import guard_helpers as g
from .guard_helpers import CAPTURE_MODES, CHAIN, POLICY_VERSION, Scenario


@pytest.fixture(params=CAPTURE_MODES)
async def scenario(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Scenario:
    return await g.run_scenario(tmp_path, monkeypatch, capture_on=request.param == "capture_on")


def _assert_capture_ran(s: Scenario) -> None:
    """The ON run really captured (and really failed one wrap); OFF captured nothing."""
    captured = s.message_for(g.CAPTURED_EVENT).data["payload_ref"]
    dropped = s.message_for(g.WRAP_FAILED_EVENT).data["payload_ref"]
    snap = s.capture.stats.snapshot()
    if s.capture_on:
        assert captured["redaction_state"] == "redacted"
        assert captured["capture_policy_version"] == POLICY_VERSION
        assert dropped["redaction_state"] == "redaction_failed"
        assert snap["captured"] == 1
        assert snap["capture_failed"] == {"key_wrap_failed": 1}
    else:
        assert captured is None
        assert dropped is None
        assert snap["captured"] == 0
        assert s.store.index_backend.documents == {}


# --- guard 1: contract ----------------------------------------------------------------------------


async def test_contract_accepts_published_events_and_rejects_any_body(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    for message in scenario.messages:
        event = json.loads(message.to_bytes())["data"]
        errors = g.telemetry_schema_errors(event)
        assert errors == []

        mark = scenario.issued.canary()
        top_level = {**copy.deepcopy(event), "prompt": mark}
        top_errors = g.telemetry_schema_errors(top_level)
        assert top_errors != []

        base_ref = event["payload_ref"] or {
            "pointer": "interaction:x",
            "redaction_state": "redacted",
        }
        for key in ("text", "response", "prompt", "content"):
            with_ref = copy.deepcopy(event)
            with_ref["payload_ref"] = {**base_ref, key: mark}
            ref_errors = g.telemetry_schema_errors(with_ref)
            assert ref_errors != [], key


# --- guard 2: edge --------------------------------------------------------------------------------


async def test_edge_messages_are_body_free(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    published = scenario.published
    assert len(published) == 3
    for raw in published:
        fields = find_body_fields(json.loads(raw))
        assert fields == []
        g.assert_no_leak(raw.decode(), scenario.issued.probes(), "a published hub message")

    if scenario.capture_on:
        # The captured content was redacted before it was encrypted and stored.
        ref = scenario.message_for(g.CAPTURED_EVENT).data["payload_ref"]
        content = await scenario.store.read_content(g.CUSTOMER, g.DOMAIN, ref["interaction_id"])
        stored = content.model_dump_json()
        g.assert_no_leak(stored, scenario.issued.credentials, "stored content")
        prefix = scenario.credential[: g.CREDENTIAL_PREFIX_CHARS]
        assert prefix not in stored
        assert "[[ns-redacted:" in stored


# --- guards 3 and 4: worker pipeline and quarantine -----------------------------------------------


async def test_worker_accepts_events_and_quarantines_bodies(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    published = scenario.published
    smuggled = g.with_body(published[0], scenario.issued, scenario.credential)

    result, sinks = await g.run_worker([*published, smuggled])

    assert result.accepted == len(published)
    assert result.quarantined == {QuarantineReason.BODY_FIELD_PRESENT: 1}
    (record,) = sinks.quarantine.effects.values()
    assert record.reason is QuarantineReason.BODY_FIELD_PRESENT
    accepted_ids = {event.message.event_id for event in sinks.ledger.effects.values()}
    assert {g.CAPTURED_EVENT, g.WRAP_FAILED_EVENT} <= accepted_ids


async def test_quarantine_record_is_body_free(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    published = scenario.published
    smuggled = g.with_body(published[0], scenario.issued, scenario.credential)
    _result, sinks = await g.run_worker([smuggled])
    (record,) = sinks.quarantine.effects.values()
    assert record.payload is not None
    payload_fields = find_body_fields(record.payload)
    assert payload_fields == []
    g.assert_no_leak(record.model_dump_json(), scenario.issued.probes(), "the quarantine record")

    container = g.FakeBlobContainer()
    await BlobQuarantineSink(container).write(record)
    (blob,) = container.blobs.values()
    g.assert_no_leak(blob.decode(), scenario.issued.probes(), "the quarantine blob")
    g.assert_no_leak(json.dumps(container.metadata), scenario.issued.probes(), "blob metadata")


# --- guard 5: archive -----------------------------------------------------------------------------


async def test_archive_record_is_body_free(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    _result, sinks = await g.run_worker(scenario.published)
    events = list(sinks.archive.effects.values())
    assert len(events) == 3
    key = secrets.token_bytes(32)
    for event in events:
        record = redact_record(event.model_dump(mode="json"), key)
        fields = find_body_fields(record)
        assert fields == []
        g.assert_no_leak(json.dumps(record), scenario.issued.probes(), "an archive record")
        blob = build_blob(event, key)
        g.assert_no_leak(gzip.decompress(blob.data).decode(), scenario.issued.probes(), "a blob")


async def test_archive_strips_a_body_that_reaches_it(scenario: Scenario) -> None:
    """``redact_record`` itself drops bodies: feed it an event with canary bodies put back."""
    _assert_capture_ran(scenario)
    _result, sinks = await g.run_worker(scenario.published)
    event = next(
        e for e in sinks.archive.effects.values() if e.message.event_id == g.CAPTURED_EVENT
    )
    issued = scenario.issued
    data = {
        **event.message.data,
        "prompt": f"{issued.canary()} archived {scenario.credential}",
        "gen_ai.output.messages": [{"role": "assistant", "content": issued.canary()}],
    }
    # model_copy skips validation: this is the shape a guard bypass upstream would produce.
    bodied = event.model_copy(update={"message": event.message.model_copy(update={"data": data})})
    document = bodied.model_dump(mode="json")
    planted = find_body_fields(document)
    assert planted != []
    key = secrets.token_bytes(32)

    record = redact_record(document, key)
    fields = find_body_fields(record)
    assert fields == []
    g.assert_no_leak(json.dumps(record), issued.probes(), "a redacted archive record")

    blob = build_blob(bodied, key)
    decoded = json.loads(gzip.decompress(blob.data))
    blob_fields = find_body_fields(decoded)
    assert blob_fields == []
    g.assert_no_leak(json.dumps(decoded), issued.probes(), "an archive blob")


# --- guard 6: audit seal --------------------------------------------------------------------------


async def test_audit_records_are_metadata_only_and_sealed(scenario: Scenario) -> None:
    _assert_capture_ran(scenario)
    drafts = scenario.audit.drafts
    records = await scenario.audit_records()
    if not scenario.capture_on:
        assert drafts == []
        assert records == []
        return

    operations = [draft.operation for _chain, draft in drafts]
    assert operations == ["interaction.capture", "interaction.capture_dropped"]
    for chain_id, draft in drafts:
        assert chain_id == CHAIN
        g.assert_audit_draft_metadata_only(draft)
        g.assert_no_leak(draft.model_dump_json(), scenario.issued.probes(), "an audit draft")

    assert [r.operation for r in records] == operations
    verification = verify_chain(records, chain_id=CHAIN)
    assert verification.ok
    for record in records:
        document = record.model_dump(mode="json")
        assert_metadata_only(document)
        g.assert_no_leak(json.dumps(document), scenario.issued.probes(), "a sealed audit record")


async def test_audit_refuses_a_draft_with_captured_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative case: a capture draft whose free-text detail carries content never seals.

    ON only: the OFF run writes no draft to tamper with.
    """
    scenario = await g.run_scenario(tmp_path, monkeypatch, capture_on=True)
    _chain, draft = scenario.audit.drafts[0]
    before = await scenario.audit_records()
    detail = f"user said {scenario.issued.canary()} with {scenario.credential}"
    outcome = draft.outcome
    assert outcome is not None
    tampered = draft.model_copy(update={"outcome": outcome.model_copy(update={"detail": detail})})

    with pytest.raises(InvalidSchemaError) as direct:
        assert_metadata_only(tampered.model_dump(mode="json"))
    assert direct.value.reason == "audit_content_rejected"

    with pytest.raises(InvalidSchemaError) as sealed:
        await scenario.audit.append(CHAIN, tampered)
    assert sealed.value.reason == "audit_content_rejected"
    g.assert_no_leak(str(sealed.value), scenario.issued.probes(), "the refusal message")

    after = await scenario.audit_records()
    assert len(after) == len(before)
    g.assert_no_leak(
        json.dumps([r.model_dump(mode="json") for r in after]),
        scenario.issued.probes(),
        "the audit chain after a refusal",
    )
