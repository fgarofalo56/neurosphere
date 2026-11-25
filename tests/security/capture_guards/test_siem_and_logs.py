"""PRP-103 criterion 7: SIEM events and log records stay free of captured content.

The SIEM check exports every audit record the capture path sealed. The log check wraps
``logging.Logger.handle`` for the test's duration, with every logger enabled at every level,
so it sees each record any logger makes (including loggers created later and loggers that do
not propagate) before filters or handlers run. It covers the whole scenario, which includes
the injected key-wrap failure, and searches message, args and exc_info of every record.
"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Iterator
from pathlib import Path

import pytest
from neurosphere_core.audit import to_siem_event

from . import guard_helpers as g
from .guard_helpers import CAPTURE_MODES


@pytest.mark.parametrize("mode", CAPTURE_MODES)
async def test_siem_events_carry_no_captured_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    s = await g.run_scenario(tmp_path, monkeypatch, capture_on=mode == "capture_on")
    records = await s.audit_records()
    assert len(records) == (2 if s.capture_on else 0)
    for record in records:
        event = to_siem_event(record)
        g.assert_no_leak(json.dumps(event), s.issued.probes(), "a SIEM event")


@pytest.fixture
def all_log_records(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[logging.LogRecord]]:
    """Every record any logger handles while the test runs, whatever its level or handlers."""
    seen: list[logging.LogRecord] = []
    original_handle = logging.Logger.handle

    def recording_handle(self: logging.Logger, record: logging.LogRecord) -> None:
        seen.append(record)
        original_handle(self, record)

    def always_enabled(self: logging.Logger, level: int) -> bool:
        del self, level
        return True

    monkeypatch.setattr(logging.Logger, "handle", recording_handle)
    monkeypatch.setattr(logging.Logger, "isEnabledFor", always_enabled)
    yield seen


def _record_text(record: logging.LogRecord) -> str:
    parts = [record.getMessage(), repr(record.msg), repr(record.args)]
    if record.exc_info:
        parts.append("".join(traceback.format_exception(*record.exc_info)))
    if record.exc_text:
        parts.append(record.exc_text)
    if record.stack_info:
        parts.append(record.stack_info)
    parts.append(repr(record.__dict__))
    return "\n".join(parts)


@pytest.mark.parametrize("mode", CAPTURE_MODES)
async def test_no_log_record_carries_captured_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_log_records: list[logging.LogRecord],
    mode: str,
) -> None:
    s = await g.run_scenario(tmp_path, monkeypatch, capture_on=mode == "capture_on")
    if s.capture_on:
        # The failure path really ran inside the recorded window.
        assert s.capture.stats.snapshot()["capture_failed"] == {"key_wrap_failed": 1}
        published = s.published
        smuggled = g.with_body(published[0], s.issued, s.credential)
        await g.run_worker([*published, smuggled])
        # Non-vacuity: the recorder saw the run's logging, so an empty result means "clean".
        assert len(all_log_records) >= 1

    for record in all_log_records:
        g.assert_no_leak(_record_text(record), s.issued.probes(), f"log record {record.name}")
