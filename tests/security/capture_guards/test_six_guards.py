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
        g.assert_no_leak(raw.decode(), scenario.issued.values, "a published hub message")

    if scenario.capture_on:
        # The captured content was redacted before it was encrypted and stored.
        ref = scenario.message_for(g.CAPTURED_EVENT).data["payload_ref"]
        content = await scenario.store.read_content(g.CUSTOMER, g.DOMAIN, ref["interaction_id"])
        stored = content.model_dump_json()
        assert scenario.credential not in stored
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
    published = scenario.published
    smuggled = g.with_body(published[0], scenario.issued, scenario.credential)
    _result, sinks = await g.run_worker([smuggled])
    (record,) = sinks.quarantine.effects.values()
    assert record.payload is not None
    payload_fields = find_body_fields(record.payload)
    assert payload_fields == []
    g.assert_no_leak(record.model_dump_json(), scenario.issued.values, "the quarantine record")

    container = g.FakeBlobContainer()
    await BlobQuarantineSink(container).write(record)
    (blob,) = container.blobs.values()
    g.assert_no_leak(blob.decode(), scenario.issued.values, "the quarantine blob")
    g.assert_no_leak(json.dumps(container.metadata), scenario.issued.values, "blob metadata")


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
        g.assert_no_leak(json.dumps(record), scenario.issued.values, "an archive record")
        blob = build_blob(event, key)
        g.assert_no_leak(gzip.decompress(blob.data).decode(), scenario.issued.values, "a blob")


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
        g.assert_no_leak(draft.model_dump_json(), scenario.issued.values, "an audit draft")

    assert [r.operation for r in records] == operations
    verification = verify_chain(records, chain_id=CHAIN)
    assert verification.ok
    for record in records:
        document = record.model_dump(mode="json")
        assert_metadata_only(document)
        g.assert_no_leak(json.dumps(document), scenario.issued.values, "a sealed audit record")
