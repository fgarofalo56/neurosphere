"""Replay API (PRP-18 item 5): read-only inspection of stored, redacted traces.

Public API: :func:`register` (router hook, prefix ``/api/v1/replay``), :func:`build_router`,
:class:`TraceReader` with :class:`InMemoryTraceReader` and :class:`ArchiveTraceReader`,
:class:`PayloadPolicy`. ``app.state.trace_reader`` is required (503 when unset);
``app.state.replay_payload_policy`` is optional (bodies off by default).

This package must not import any action executor or connector; see
``services/api/tests/replay/test_replay_readonly.py``.
"""

from neurosphere_api.replay.dependencies import PayloadPolicy, get_payload_policy, get_trace_reader
from neurosphere_api.replay.reader import (
    ArchiveTraceReader,
    InMemoryTraceReader,
    SpanRecord,
    TraceReader,
    TraceRecords,
)
from neurosphere_api.replay.router import PREFIX, build_router, register

__all__ = [
    "PREFIX",
    "ArchiveTraceReader",
    "InMemoryTraceReader",
    "PayloadPolicy",
    "SpanRecord",
    "TraceReader",
    "TraceRecords",
    "build_router",
    "get_payload_policy",
    "get_trace_reader",
    "register",
]
