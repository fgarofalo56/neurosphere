"""PRP-103 criterion 7: SIEM events and log records stay free of captured content.

The SIEM check exports every audit record the capture path sealed. The log check captures
DEBUG over every logger (propagating or not) for the whole scenario, which includes the
injected key-wrap failure, and searches message, args and exc_info of every record.
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
        g.assert_no_leak(json.dumps(event), s.issued.values, "a SIEM event")


@pytest.fixture
def every_logger(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """DEBUG on the root and every known logger; non-propagating loggers feed caplog too."""
    caplog.set_level(logging.DEBUG)
    detached: list[logging.Logger] = []
    for name, logger in list(logging.root.manager.loggerDict.items()):
        if not isinstance(logger, logging.Logger):
            continue
        caplog.set_level(logging.DEBUG, logger=name)
        if not logger.propagate:
            logger.addHandler(caplog.handler)
            detached.append(logger)
    try:
        yield caplog
    finally:
        for logger in detached:
            logger.removeHandler(caplog.handler)


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
    every_logger: pytest.LogCaptureFixture,
    mode: str,
) -> None:
    s = await g.run_scenario(tmp_path, monkeypatch, capture_on=mode == "capture_on")
    if s.capture_on:
        # The failure path really ran inside the captured window.
        assert s.capture.stats.snapshot()["capture_failed"] == {"key_wrap_failed": 1}
        published = s.published
        smuggled = g.with_body(published[0], s.issued, s.credential)
        await g.run_worker([*published, smuggled])

    for record in every_logger.records:
        g.assert_no_leak(_record_text(record), s.issued.values, f"log record {record.name}")
    g.assert_no_leak(every_logger.text, s.issued.values, "the captured log text")
