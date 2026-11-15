"""Runtime health of the SIEM export sinks (PRP-40 item 1).

The exporter reports every delivery outcome here. Only reason CODES are kept (``[a-z_]``), never
an exception message, host, hub name or key, so the status route can show this object verbatim.
A sink failure never fails the audit append; this object is how an operator finds out.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

__all__ = [
    "REASON_AUTH_FAILED",
    "REASON_EVENT_BUILD_FAILED",
    "REASON_SINK_ERROR",
    "REASON_SINK_TIMEOUT",
    "REASON_SINK_UNAVAILABLE",
    "SiemHealthSnapshot",
    "SiemSinkHealth",
    "failure_reason",
]

REASON_EVENT_BUILD_FAILED: Final = "event_build_failed"
REASON_SINK_TIMEOUT: Final = "sink_timeout"
REASON_AUTH_FAILED: Final = "sink_auth_failed"
REASON_SINK_UNAVAILABLE: Final = "sink_unavailable"
REASON_SINK_ERROR: Final = "sink_error"

#: Exception class names (anywhere in the MRO) mapped to reason codes. Names, not imports, so
#: this module does not pull in the Azure SDKs; matching on names never reads a message.
_BY_TYPE_NAME: Final = (
    ("ClientAuthenticationError", REASON_AUTH_FAILED),
    ("AuthenticationError", REASON_AUTH_FAILED),
    ("CredentialUnavailableError", REASON_AUTH_FAILED),
    ("ConnectionError", REASON_SINK_UNAVAILABLE),
    ("ConnectError", REASON_SINK_UNAVAILABLE),
    ("EventHubError", REASON_SINK_UNAVAILABLE),
    ("OSError", REASON_SINK_UNAVAILABLE),
)


def failure_reason(exc: BaseException) -> str:
    """A reason code for ``exc``; the message is never inspected."""
    if isinstance(exc, TimeoutError):
        return REASON_SINK_TIMEOUT
    names = {cls.__name__ for cls in type(exc).__mro__}
    for name, reason in _BY_TYPE_NAME:
        if name in names:
            return reason
    return REASON_SINK_ERROR


@dataclass(frozen=True, slots=True)
class SiemHealthSnapshot:
    """A consistent copy of the counters (what the status route serialises)."""

    sink: str
    state: str
    reason: str | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    total_failures: int
    total_sent: int
    last_failure_reason: str | None


class SiemSinkHealth:
    """Counters for one configured sink kind (``none``, ``stdout``, ``file``, ``eventhubs``).

    ``state`` and ``reason`` are the composition outcome (``ok``, ``disabled`` or ``failed`` with
    a reason code such as ``audit_siem_settings_invalid``); the counters are runtime delivery.
    """

    def __init__(
        self,
        sink: str,
        *,
        state: str = "ok",
        reason: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sink = sink
        self._state = state
        self._config_reason = reason
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._consecutive = 0
        self._failures = 0
        self._sent = 0
        self._reason: str | None = None

    @property
    def sink(self) -> str:
        return self._sink

    def record_success(self) -> None:
        with self._lock:
            self._last_success_at = self._clock()
            self._consecutive = 0
            self._sent += 1

    def record_failure(self, reason: str) -> None:
        with self._lock:
            self._last_failure_at = self._clock()
            self._consecutive += 1
            self._failures += 1
            self._reason = reason

    def snapshot(self) -> SiemHealthSnapshot:
        with self._lock:
            return SiemHealthSnapshot(
                sink=self._sink,
                state=self._state,
                reason=self._config_reason,
                last_success_at=self._last_success_at,
                last_failure_at=self._last_failure_at,
                consecutive_failures=self._consecutive,
                total_failures=self._failures,
                total_sent=self._sent,
                last_failure_reason=self._reason,
            )
