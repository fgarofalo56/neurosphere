"""Malformed messages: closed-enum reasons, attempts=1, and no body ever reaches quarantine."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from neurosphere_core.payload import find_body_fields
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.reasons import QuarantineReason

from sandbox.bad_events import MALFORMED_MUTATIONS, _malform

from .support import (
    T0,
    Doc,
    Harness,
    hub_message,
    raw_event,
    raw_from_bytes,
    raw_json,
    settings,
    telemetry_at,
)

SECRET = "SECRET-PROMPT-TEXT"  # noqa: S105 - a marker string, not a credential


async def _single(harness: Harness, raw, **kw):  # type: ignore[no-untyped-def]
    result = await process_batch([raw], harness.deps(), settings(**kw))
    assert len(harness.quarantine.effects) == 1
    assert not harness.archive.effects
    assert not harness.ledger.effects
    return result, next(iter(harness.quarantine.effects.values()))


async def test_not_json_is_invalid_wire_and_stores_no_body(harness: Harness) -> None:
    body = b'{"prompt": "' + SECRET.encode() + b'", "oops": '  # truncated JSON
    result, record = await _single(harness, raw_from_bytes(body, 0))

    assert record.reason is QuarantineReason.INVALID_WIRE
    assert record.attempts == 1
    assert record.payload is None
    assert record.payload_sha256 == hashlib.sha256(body).hexdigest()
    assert record.payload_bytes == len(body)
    assert SECRET not in record.model_dump_json()
    assert result.quarantined == {QuarantineReason.INVALID_WIRE: 1}


async def test_invalid_utf8_is_invalid_wire(harness: Harness) -> None:
    _, record = await _single(harness, raw_from_bytes(b"\xff\xfe\x00bad", 0))
    assert record.reason is QuarantineReason.INVALID_WIRE


async def test_json_that_is_not_a_hub_message_is_invalid_wire(harness: Harness) -> None:
    _, record = await _single(harness, raw_json({"hello": "world"}, 0))

    assert record.reason is QuarantineReason.INVALID_WIRE
    assert record.payload == {"hello": "world"}  # parsed JSON, body fields already dropped


async def test_scalar_json_stores_hash_only(harness: Harness) -> None:
    _, record = await _single(harness, raw_from_bytes(b'"just a string"', 0))

    assert record.reason is QuarantineReason.INVALID_WIRE
    assert record.payload is None
    assert record.payload_sha256 is not None


async def test_depth_exceeded_stores_no_body(harness: Harness) -> None:
    body = b"[" * 200 + SECRET.encode().join([b'"', b'"']) + b"]" * 200
    _, record = await _single(harness, raw_from_bytes(body, 0))

    assert record.reason is QuarantineReason.DEPTH_EXCEEDED
    assert record.payload is None
    assert record.payload_bytes == len(body)


async def test_body_field_present_is_quarantined_with_body_dropped(
    harness: Harness, template: Doc
) -> None:
    doc = telemetry_at(template, "evt-body", T0)
    wire = json.loads(hub_message(doc).to_bytes())
    wire["data"]["attributes"] = {"nested": [{"prompt": SECRET}]}
    wire["response"] = SECRET

    _, record = await _single(harness, raw_json(wire, 0))

    assert record.reason is QuarantineReason.BODY_FIELD_PRESENT
    assert record.payload is not None
    assert find_body_fields(record.payload) == []
    assert SECRET not in record.model_dump_json()
    assert record.event_id == "evt-body"  # identifiers survive for triage


@pytest.mark.parametrize("mutation", [m for m in MALFORMED_MUTATIONS if m != "unknown_field"])
async def test_sandbox_malformed_mutations_are_invalid_schema(
    harness: Harness, template: Doc, mutation: str
) -> None:
    bad = _malform(telemetry_at(template, "evt-bad", T0), mutation)
    wire = json.loads(hub_message(telemetry_at(template, "evt-bad", T0)).to_bytes())
    wire["data"] = bad
    if mutation == "missing_required_field":
        wire["data"] = bad  # cloud removed from the contract data, message cloud intact

    _, record = await _single(harness, raw_json(wire, 0))

    assert record.reason is QuarantineReason.INVALID_SCHEMA
    assert record.attempts == 1


async def test_unknown_field_is_unsupported_schema_version(harness: Harness, template: Doc) -> None:
    bad = _malform(telemetry_at(template, "evt-unk", T0), "unknown_field")
    wire = json.loads(hub_message(telemetry_at(template, "evt-unk", T0)).to_bytes())
    wire["data"] = bad

    _, record = await _single(harness, raw_json(wire, 0))

    assert record.reason is QuarantineReason.UNSUPPORTED_SCHEMA_VERSION


async def test_unknown_major_version_is_unsupported_schema_version(
    harness: Harness, template: Doc
) -> None:
    doc = {**telemetry_at(template, "evt-v2", T0), "schema_version": "2.0.0"}

    _, record = await _single(harness, raw_event(doc, 0))

    assert record.reason is QuarantineReason.UNSUPPORTED_SCHEMA_VERSION


async def test_missing_schema_version_is_invalid_schema(harness: Harness, template: Doc) -> None:
    doc = copy.deepcopy(telemetry_at(template, "evt-nov", T0))
    del doc["schema_version"]

    _, record = await _single(harness, raw_event(doc, 0))

    assert record.reason is QuarantineReason.INVALID_SCHEMA


async def test_message_cloud_other_than_worker_cloud(harness: Harness, template: Doc) -> None:
    harness.cloud = "government"

    _, record = await _single(harness, raw_event(telemetry_at(template, "evt-cloud", T0), 0))

    assert record.reason is QuarantineReason.CLOUD_MISMATCH


async def test_data_cloud_other_than_message_cloud(harness: Harness, template: Doc) -> None:
    doc = {**telemetry_at(template, "evt-cloud2", T0), "cloud": "government"}

    _, record = await _single(harness, raw_event(doc, 0, cloud="commercial"))

    assert record.reason is QuarantineReason.CLOUD_MISMATCH


async def test_envelope_identity_must_match_contract(harness: Harness, template: Doc) -> None:
    doc = telemetry_at(template, "evt-ident", T0)

    _, record = await _single(harness, raw_event(doc, 0, customer_id="someone-else"))

    assert record.reason is QuarantineReason.INVALID_SCHEMA


async def test_malformed_message_does_not_block_the_batch(harness: Harness, template: Doc) -> None:
    good = telemetry_at(template, "evt-good", T0)
    batch = [raw_from_bytes(b"garbage", 0), raw_event(good, 1)]

    result = await process_batch(batch, harness.deps(), settings())

    assert (result.accepted, result.quarantined_total) == (1, 1)
    assert result.checkpoint == "0:1"
    assert not harness.sleeps  # malformed messages are never retried


async def test_quarantine_is_idempotent_on_redelivery(harness: Harness) -> None:
    raw = raw_from_bytes(b"garbage", 0)

    await process_batch([raw], harness.deps(), settings())
    await process_batch([raw], harness.deps(), settings())

    assert len(harness.quarantine.effects) == 1
    assert harness.quarantine.write_calls == 2


def test_reason_codes_are_the_closed_set() -> None:
    assert {r.value for r in QuarantineReason} == {
        "invalid_wire",
        "depth_exceeded",
        "invalid_schema",
        "unsupported_schema_version",
        "body_field_present",
        "cloud_mismatch",
        "retry_budget_exhausted",
    }
