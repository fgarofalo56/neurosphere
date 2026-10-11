"""Deterministic NDJSON writing."""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self


def dumps(doc: Any) -> bytes:
    """Canonical one-line JSON (sorted keys, ASCII, no spaces) terminated by a single LF."""
    return (
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        + b"\n"
    )


class NdjsonWriter:
    """Append-only writer that streams records and counts lines. LF newlines on every OS."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0
        self._fh: BinaryIO | None = None

    def __enter__(self) -> Self:
        self._fh = self.path.open("wb")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write_doc(self, doc: Any) -> None:
        self.write_line(dumps(doc))

    def write_line(self, line: bytes) -> None:
        assert self._fh is not None
        self._fh.write(line)
        self.count += 1


def write_json(path: Path, doc: Any) -> None:
    path.write_bytes(
        (json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    )
