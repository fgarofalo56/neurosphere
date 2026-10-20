"""Where the sampler reads redacted archive records from (PRP-16 item 2).

A ``RecordSource`` yields archive-shaped records: telemetry already redacted by the PRP-07 archive
(bodies dropped, people pseudonymized). Two implementations ship: in memory and NDJSON. An Azure
blob reader over the archive container is OPEN: it needs a live Azurite or storage account and the
worker runtime host (also OPEN), so it is not built here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from neurosphere_core.errors import InvalidSchemaError

__all__ = ["InMemoryRecordSource", "NdjsonRecordSource", "RecordSource"]


@runtime_checkable
class RecordSource(Protocol):
    def records(self) -> AsyncIterator[Mapping[str, Any]]: ...


class InMemoryRecordSource:
    def __init__(self, records: Iterable[Mapping[str, Any]]) -> None:
        self._records = list(records)

    async def records(self) -> AsyncIterator[Mapping[str, Any]]:
        for record in self._records:
            yield record


class NdjsonRecordSource:
    """One JSON object per line; blank lines are ignored, a malformed line is rejected."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    async def records(self) -> AsyncIterator[Mapping[str, Any]]:
        with self._path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    raise InvalidSchemaError(
                        f"line {number} is not valid JSON", reason="ndjson_line_invalid"
                    ) from None
                if not isinstance(record, dict):
                    raise InvalidSchemaError(
                        f"line {number} is not a JSON object", reason="ndjson_line_invalid"
                    )
                yield record
