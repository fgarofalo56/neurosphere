"""Scan test: whatever the pipeline quarantines, no prompt/response field reaches a blob."""

from __future__ import annotations

import json
from typing import Any

from neurosphere_core.payload import find_body_fields
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import (
    T0,
    Doc,
    FakeBlobContainer,
    Harness,
    blob_sink,
    raw_event,
    raw_from_bytes,
    settings,
    telemetry_at,
)

_SENTINEL = "SYNTHETIC-PROMPT-SENTINEL"


def _leak(doc: Doc, offset: int) -> RawMessage:
    """A wire message whose data carries body fields (HubMessage itself refuses to build one)."""
    wire = json.loads(raw_event(doc, offset).body)
    wire["data"]["prompt"] = _SENTINEL
    wire["data"]["nested"] = {"response": _SENTINEL, "gen_ai.input.messages": [_SENTINEL]}
    wire["data"]["attrs"] = [{"key": "llm.prompt", "value": {"stringValue": _SENTINEL}}]
    return raw_from_bytes(json.dumps(wire).encode(), offset)


async def test_no_quarantined_blob_contains_body_fields(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    leaky = _leak(telemetry_at(template, "evt-leak", T0), 0)
    bad = telemetry_at(template, "evt-bad", T0)
    bad["input_tokens"] = "not-a-number"
    bad_schema = _leak(bad, 1)
    poison = telemetry_at(template, "evt-poison-scan", T0)
    harness.archive.fail_transient(3)
    deps = harness.deps()
    deps.quarantine = blob_sink(container)

    await process_batch(
        [
            leaky,
            bad_schema,
            raw_from_bytes(json.dumps({"prompt": _SENTINEL, "x": 1}).encode(), 2),
            raw_from_bytes(f"not json {_SENTINEL}".encode(), 3),
            raw_event(poison, 4),
        ],
        deps,
        settings(),
    )

    names = container.names("records/")
    assert len(names) >= 4
    for name in names:
        raw = container.blobs[name]
        assert _SENTINEL.encode() not in raw, name
        stored: Any = json.loads(raw)
        assert not find_body_fields(stored), name
