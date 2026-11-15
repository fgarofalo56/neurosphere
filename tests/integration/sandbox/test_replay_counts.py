# pyright: reportMissingImports=false
"""Replay delivers every telemetry line, bad events included, exactly as the manifest lists."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from sbx_cli import order_lines
from sbx_seam import HubSeam

from .conftest import cli_json

CONSUMER_GROUP = "normalizer"


def _payload(body: bytes) -> bytes:
    """The generator line a delivered body carries: unwrap a ``HubMessage`` envelope."""
    try:
        doc = json.loads(body)
    except ValueError:
        return body
    if isinstance(doc, dict) and "wire_version" in doc and "data" in doc:
        return json.dumps(doc["data"], sort_keys=True).encode()
    return json.dumps(doc, sort_keys=True).encode() if isinstance(doc, dict) else body


def test_order_lines_options_offline() -> None:
    a = b'{"event_time":"2026-10-01T00:00:02Z"}'
    b = b'{"event_time":"2026-10-01T00:00:01Z"}'
    bad = b"{not json"
    assert order_lines([a, bad, b], "arrival") == [a, bad, b]
    assert order_lines([a, bad, b], "reverse") == [b, bad, a]
    assert order_lines([a, bad, b], "event-time") == [b, a, bad]


@pytest.mark.integration
def test_replay_counts_match_bad_event_manifest(empty_hub: None, data_dir: Path) -> None:
    lines = [
        raw.rstrip(b"\r\n")
        for raw in (data_dir / "telemetry.ndjson").read_bytes().splitlines(keepends=True)
        if raw.strip()
    ]
    bad = json.loads((data_dir / "bad-event-manifest.json").read_text(encoding="utf-8"))
    expected = bad["expected"]
    entries = [
        json.loads(x)
        for x in (data_dir / "bad-event-manifest.ndjson").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    assert len(lines) == expected["total_lines"]

    result = cli_json("replay", "--data-dir", str(data_dir), "--order", "arrival")
    assert result["events"]["sent"] == expected["total_lines"]

    bodies = HubSeam().consume(CONSUMER_GROUP, expected["total_lines"], timeout=90)
    assert len(bodies) == expected["total_lines"]
    # Multiset equality: nothing lost, nothing invented, duplicates delivered as duplicates.
    # Replay wraps parseable lines in the ingestion envelope (#162), so compare the payloads.
    assert Counter(_payload(body) for body in bodies) == Counter(_payload(x) for x in lines)

    duplicate_lines = [e["line"] for e in entries if e["kind"] == "duplicate"]
    malformed_lines = [e["line"] for e in entries if e["kind"] == "malformed"]
    assert len(duplicate_lines) == expected["duplicate_lines"]
    assert len(malformed_lines) == expected["malformed_lines"]
    # Byte-identical re-deliveries: surplus over distinct bodies equals the duplicate count.
    payloads = [_payload(body) for body in bodies]
    assert len(payloads) - len(set(payloads)) == expected["duplicate_lines"]
    # Malformed lines (1-based) are present verbatim.
    delivered = Counter(payloads)
    for number in malformed_lines:
        assert delivered[_payload(lines[number - 1])] >= 1

    # A repeat replay is a no-op, so counts stay exact.
    again = cli_json("replay", "--data-dir", str(data_dir))
    assert again["events"]["sent"] == 0
    assert HubSeam().event_count() == expected["total_lines"]
