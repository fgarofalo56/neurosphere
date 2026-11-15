"""``AgentSeriesSource`` over the redacted archive (PRP-15 round 2, assumption A4).

``ArchiveSeriesSource.load`` reads the archive blobs of a bounded UTC day window (telemetry and
cost documents, ``{customer}/{domain}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz``) once, asynchronously,
then serves the snapshot through the synchronous ``AgentSeriesSource`` protocol. Bucketing, dedupe
and coverage rules are the sandbox rules (``SeriesAccumulator``), so equal documents give equal
series.

Fail closed: only blobs whose domain segment is in the scope are downloaded; a decoded document of
another customer, another cloud or another domain is never read into a series; a malformed blob
is skipped and counted, never fatal. Nothing but counts is logged. When the archive listing hit
its bound (``ArchiveReader.truncated``) or the per-run download bound, coverage is dropped for the
whole snapshot (unknown, never zero usage) and ``truncated`` is set so the pipeline records
``archive_truncated`` instead of emitting ``unused_agent``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.rules.sandbox_source import SeriesAccumulator
from neurosphere_workers.runtime.archive_reader import BLOB_SUFFIX, ArchiveReader

__all__ = ["ArchiveLoadStats", "ArchiveSeriesSource"]

DEFAULT_MAX_DOCS: Final = 100_000


@dataclass(slots=True)
class ArchiveLoadStats:
    listed: int = 0
    in_window: int = 0
    read: int = 0
    unreadable: int = 0
    out_of_scope: int = 0
    malformed: int = 0
    other_kind: int = 0


def _blob_parts(name: str) -> tuple[str, date] | None:
    """``(domain segment, day)`` of ``{customer}/{domain}/{yyyy}/{mm}/{dd}/{doc}.json.gz``."""
    parts = name.split("/")
    if len(parts) != 6 or not parts[5].endswith(BLOB_SUFFIX):
        return None
    try:
        return parts[1], date(int(parts[2]), int(parts[3]), int(parts[4]))
    except ValueError:
        return None


class ArchiveSeriesSource(SeriesAccumulator):
    """Snapshot of archive telemetry and cost for one scope and window."""

    def __init__(self) -> None:
        super().__init__()
        self.archive_stats = ArchiveLoadStats()
        self.truncated = False
        self.window: tuple[date, date] | None = None

    @classmethod
    async def load(
        cls,
        reader: ArchiveReader,
        *,
        scope: IdentityScope,
        agents: Iterable[Mapping[str, Any]],
        owners: Mapping[str, str],
        window: tuple[date, date],
        max_docs: int = DEFAULT_MAX_DOCS,
    ) -> ArchiveSeriesSource:
        """``agents`` are catalog agent documents (``id``, ``cloud``, ``customer_id``,
        ``domain_id``, ``lifecycle_status``, ``created_at``); ``owners`` maps agent id to owner."""
        source = cls()
        source.window = window
        allowed = frozenset(scope.allowed_domains)
        for doc in agents:
            ident = doc.get("id")
            if (
                isinstance(ident, str)
                and doc.get("cloud") == scope.cloud
                and doc.get("customer_id") == scope.customer_id
                and doc.get("domain_id") in allowed
            ):
                source._agents[ident] = dict(doc)
        source._owners = dict(owners)
        await source._read(reader, scope, allowed, window, max_docs)
        return source

    async def _read(
        self,
        reader: ArchiveReader,
        scope: IdentityScope,
        allowed: frozenset[str],
        window: tuple[date, date],
        max_docs: int,
    ) -> None:
        stats = self.archive_stats
        names = await reader.names(scope.customer_id)
        stats.listed = len(names)
        start, end = window
        wanted: list[tuple[str, str]] = []
        for doc_id, name in names.items():
            parts = _blob_parts(name)
            if parts is None or not name.startswith(f"{scope.customer_id}/"):
                continue
            domain, day = parts
            if domain not in allowed:
                stats.out_of_scope += 1
                continue
            if start <= day < end:
                wanted.append((name, doc_id))
        wanted.sort()
        stats.in_window = len(wanted)
        if len(wanted) > max_docs:
            self.truncated = True
            wanted = wanted[:max_docs]
        for name, _doc_id in wanted:
            doc = await reader.read(scope.customer_id, name)
            if doc is None:
                stats.unreadable += 1
                continue
            self._ingest(doc, scope, allowed)
        self.finish_cost()
        if reader.truncated:
            self.truncated = True
        if self.truncated:
            # Part of the archive was not seen: every day is unknown, never zero usage.
            self._tele_cover.clear()
            self._cost_cover.clear()

    def _ingest(
        self, doc: Mapping[str, Any], scope: IdentityScope, allowed: frozenset[str]
    ) -> None:
        stats = self.archive_stats
        message = doc.get("message")
        contract = doc.get("contract")
        if not isinstance(message, dict) or not isinstance(contract, dict):
            stats.malformed += 1
            return
        if (
            contract.get("cloud") != scope.cloud
            or contract.get("customer_id") != scope.customer_id
            or contract.get("domain_id") not in allowed
        ):
            stats.out_of_scope += 1
            return
        kind = message.get("kind")
        if kind == "telemetry":
            self.add_telemetry(contract)  # skips and duplicates are counted in ``stats``
        elif kind == "cost":
            self.add_cost(contract)
        else:
            stats.other_kind += 1
            return
        stats.read += 1


def window_ending(today: date, lookback_days: int) -> tuple[date, date]:
    """The last ``lookback_days`` complete UTC days ending before ``today``: ``[start, today)``."""
    return today - timedelta(days=lookback_days), today
