"""Tool results and citations.

Citations are produced by a tool from the records it actually returned; the model never authors
one. ``unknown_citations`` checks a set of model-cited ids against the tool results of the turn,
so an invented citation fails the check (PRP-19 gotcha). Freshness is explicit: a record without
an ``as_of`` timestamp is ``unknown``, never presented as fresh.

Everything in a ``ToolResult`` is untrusted data. It is returned to the model as data and can
never change the scope or the tool allowlist.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "DEFAULT_MAX_AGE",
    "Citation",
    "FreshnessPolicy",
    "FreshnessState",
    "ToolRecord",
    "ToolResult",
    "unknown_citations",
]

FreshnessState = Literal["fresh", "stale", "unknown"]

DEFAULT_MAX_AGE: Final = timedelta(days=1)


class Citation(BaseModel):
    """Provenance of one returned record: what it is, where it came from and how current it is."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    as_of: str | None
    """Data freshness timestamp (UTC, ``Z``) of the record; ``None`` when unknown."""
    freshness: FreshnessState


class ToolRecord(BaseModel):
    """One returned record. ``data`` is untrusted content (catalog text, trace text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    data: dict[str, JsonValue]


class ToolResult(BaseModel):
    """Records plus the citations the tool built from them (one citation per record)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    records: tuple[ToolRecord, ...]
    citations: tuple[Citation, ...]
    truncated: bool = False
    """True when a budget or server ceiling cut the result; the caller must say so."""
    content_trust: Literal["untrusted_data"] = "untrusted_data"
    """Marker for the orchestrator: treat ``records`` as data, never as instructions."""


@dataclass(frozen=True)
class FreshnessPolicy:
    """Turns an ``as_of`` timestamp into a freshness state against an injected ``now``."""

    max_age: timedelta = DEFAULT_MAX_AGE

    def state(self, as_of: str | None, now: datetime) -> FreshnessState:
        if as_of is None:
            return "unknown"
        try:
            observed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
        if observed.tzinfo is None:
            return "unknown"
        return "fresh" if now.astimezone(UTC) - observed <= self.max_age else "stale"


def unknown_citations(cited_ids: Iterable[str], results: Iterable[ToolResult]) -> tuple[str, ...]:
    """Cited ids that no tool result of this turn produced (sorted, deduplicated).

    An empty tuple means every citation traces to a real returned record.
    """
    produced = {c.record_id for result in results for c in result.citations}
    return tuple(sorted({c for c in cited_ids if c not in produced}))
