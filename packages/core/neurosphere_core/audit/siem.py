"""SIEM export hook: redacted audit events to pluggable sinks.

Records are already metadata-only (guarded at seal), but export is an external transmission,
so every event is redacted again here as defence in depth: the PRP-05 redaction filter
(bearer tokens, connection-string secrets, sensitive keys) plus audit-specific scrubbing of
JWTs, e-mail addresses / UPNs and GUID-shaped values outside server-assigned id fields, and
the internal ``snapshot_ref`` storage pointer is withheld.

Export runs after the record is durable. A failing sink is logged (sink name and audit id
only) and never fails the append: the audit store, not the SIEM, is the system of record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Final, Protocol

from neurosphere_contracts.audit.v1.audit_record import AuditRecord

from neurosphere_core.audit.content_guard import GUID
from neurosphere_core.observability import REDACTED, redact_value

SIEM_EVENT_TYPE: Final = "neurosphere.audit.v1"

_JWT: Final = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?")
_EMAIL: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_FIELDS: Final = frozenset({"audit_id", "intent_id"})
_WITHHELD_FIELDS: Final = frozenset({"snapshot_ref"})

_log = logging.getLogger(__name__)


def _scrub_text(text: str) -> str:
    text = _JWT.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return GUID.sub(REDACTED, text)


def _scrub(value: Any, key: str | None = None) -> Any:
    if key in _WITHHELD_FIELDS and value is not None:
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): _scrub(v, str(k)) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_scrub(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str) and key not in _ID_FIELDS:
        return _scrub_text(value)
    return value


def to_siem_event(record: AuditRecord) -> dict[str, Any]:
    """Redacted, flat-enough JSON event for a SIEM. Hashes are kept for chain correlation."""
    document = redact_value(record.model_dump(mode="json"))
    event = _scrub(document)
    return {"event_type": SIEM_EVENT_TYPE, "record": event}


class SiemSink(Protocol):
    """Destination for redacted audit events (Sentinel, Splunk, syslog... implement this)."""

    name: str

    async def emit(self, event: Mapping[str, Any]) -> None:
        """Deliver one already-redacted event."""
        ...


class SiemExporter:
    """Fans each record out to every sink. Never raises."""

    def __init__(self, sinks: Sequence[SiemSink], *, logger: logging.Logger | None = None) -> None:
        self._sinks = tuple(sinks)
        self._log = logger or _log
        self.failures = 0

    async def export(self, record: AuditRecord) -> None:
        event = to_siem_event(record)
        for sink in self._sinks:
            try:
                await sink.emit(event)
            except Exception:  # a sink must never block or fail the audit append
                self.failures += 1
                self._log.warning(
                    "siem sink failed", extra={"sink": sink.name, "audit_id": record.audit_id.root}
                )


def _line(event: Mapping[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


class JsonLinesFileSink:
    """Reference sink: append one JSON object per line to a local file."""

    def __init__(self, path: Path, *, name: str = "jsonl-file") -> None:
        self.name = name
        self._path = path

    def _append(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    async def emit(self, event: Mapping[str, Any]) -> None:
        await asyncio.to_thread(self._append, _line(event))


class StdoutSink:
    """Reference sink: one JSON object per line on stdout (or an injected stream)."""

    def __init__(self, stream: IO[str] | None = None, *, name: str = "stdout") -> None:
        self.name = name
        self._stream = stream

    async def emit(self, event: Mapping[str, Any]) -> None:
        stream = self._stream if self._stream is not None else sys.stdout
        stream.write(_line(event))
        stream.flush()
