"""The Event Hubs publish waits out the emulator's throttle (found on a live `make demo-up`).

The emulator answered ``server-busy`` (error code 50002, "wait 10 seconds and try again") in
the middle of the demo-world publish and the seed died with a half-published hub. No emulator
here: the send is a fake.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from azure.eventhub.exceptions import EventDataSendError

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "sandbox"
THROTTLED = (
    "The request was terminated because the entity is being throttled. Error code : 50002. "
    "Please wait 10 seconds and try again.\nError condition: com.microsoft:server-busy"
)


def _load() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # the seam imports its sibling `sbx_guard`
    try:
        spec = importlib.util.spec_from_file_location(
            "sbx_seam_under_test", SCRIPTS / "sbx_seam.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


seam = _load()


class _Send:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.sent: list[object] = []
        self.calls = 0

    def __call__(self, batch: object) -> None:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(batch)


def test_a_throttled_send_is_retried_after_the_wait_and_sent_once() -> None:
    send = _Send([EventDataSendError(message=THROTTLED), EventDataSendError(message=THROTTLED)])
    waits: list[float] = []
    seam.send_with_backoff(send, "batch", sleep=waits.append)
    assert send.sent == ["batch"]
    assert waits == [seam.THROTTLE_WAIT_SECONDS] * 2


def test_a_send_still_throttled_after_every_attempt_raises() -> None:
    send = _Send([EventDataSendError(message=THROTTLED) for _ in range(10)])
    waits: list[float] = []
    with pytest.raises(EventDataSendError):
        seam.send_with_backoff(send, "batch", sleep=waits.append, attempts=3)
    assert send.calls == 3
    assert len(waits) == 2
    assert send.sent == []


def test_any_other_send_error_is_not_retried() -> None:
    send = _Send([EventDataSendError(message="connection refused")])
    waits: list[float] = []
    with pytest.raises(EventDataSendError):
        seam.send_with_backoff(send, "batch", sleep=waits.append)
    assert send.calls == 1
    assert waits == []
