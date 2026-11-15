"""PRP-38 item 3 (#162): replay wraps valid telemetry in the ingestion envelope.

The worker validates every body as a ``HubMessage`` (``extra="forbid"``), so raw generator lines
were all quarantined as ``invalid_wire``. Valid lines are wrapped; unparseable ones stay raw.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from neurosphere_core.payload import HubMessage

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "sandbox"
sys.path.insert(0, str(SCRIPTS))

import sbx_cli  # noqa: E402  # pyright: ignore[reportMissingImports]
from sbx_wire import wrap_telemetry_line  # noqa: E402  # pyright: ignore[reportMissingImports]

RECEIVED = "2026-11-15T10:00:00.000Z"


def _doc(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "event_id": "evt-1",
        "cloud": "commercial",
        "customer_id": "synthco",
        "source_id": "src-1",
        "request_id": "req-1",
        "event_time": "2026-10-01T00:00:00Z",
    }
    doc.update(overrides)
    return doc


def test_valid_line_is_wrapped_in_a_hub_message() -> None:
    line = json.dumps(_doc()).encode()
    wrapped = wrap_telemetry_line(line, RECEIVED)
    message = HubMessage.model_validate_json(wrapped)
    assert message.event_id == "evt-1"
    assert message.kind.value == "telemetry"
    assert message.observation_kind == "gateway"
    assert message.data == _doc()


@pytest.mark.parametrize(
    "line",
    [
        b"{not json",
        b"[1, 2]",
        json.dumps({k: v for k, v in _doc().items() if k != "cloud"}).encode(),
        json.dumps(_doc(cloud="mars")).encode(),
    ],
)
def test_malformed_lines_stay_raw(line: bytes) -> None:
    assert wrap_telemetry_line(line, RECEIVED) == line


class _Hub:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def event_count(self) -> int:
        return 0

    def publish(self, lines: object, rate: float = 0.0, chunk: int = 100) -> int:
        self.sent.extend(lines)  # type: ignore[arg-type]
        return len(self.sent)


def test_publish_events_wraps_valid_and_keeps_malformed_raw(tmp_path: Path) -> None:
    good = json.dumps(_doc()).encode()
    bad = b"{not json"
    (tmp_path / "telemetry.ndjson").write_bytes(good + b"\n" + bad + b"\n" + good + b"\n")
    hub = _Hub()
    result = sbx_cli.publish_events(tmp_path, 0.0, "arrival", False, hub)  # type: ignore[arg-type]
    assert result["sent"] == 3
    assert [HubMessage.model_validate_json(x).event_id for x in (hub.sent[0], hub.sent[2])] == [
        "evt-1",
        "evt-1",
    ]
    assert hub.sent[1] == bad
