"""``AgentSeriesSource`` over sandbox generator OUTPUT FILES (never imports ``sandbox``).

Reads ``agents.ndjson``, ``relations.ndjson`` (``owned_by``), ``telemetry.ndjson`` and
``cost.ndjson`` from a directory.

Bad input never crashes the load. Telemetry and cost lines that are not JSON, fail the generated
contract model, or have no usable agent id/time are skipped and counted (``LoadStats``); telemetry
is de-duplicated by ``event_id`` (re-deliveries and out-of-order arrival do not change the result:
events are bucketed by event time, not by line position). Cost records are de-duplicated by
``dedupe_key`` so gateway, application and billing views of one call count once.

Source coverage. The "source" of an agent is the third segment of its canonical id
(``cloud:customer:<source>:agent:<id>``). Telemetry coverage of a source on a UTC day is KNOWN iff
at least one valid telemetry event attributed to an agent of that source falls on that day; cost
coverage is the same over cost records. An agent with zero events on a covered day had no usage; a
day with no events from any agent of the source is unknown (the pipeline for that source may be
down), never zero. Cost amounts are ``None`` on days without cost coverage.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from pydantic import ValidationError

from neurosphere_workers.recommendations.rules.series import (
    AgentDay,
    AgentSeries,
    bound_durations,
)

_ERROR_OUTCOMES = frozenset({"error", "timeout"})
_COST_PRIORITY = {"application": 0, "gateway": 1, "billing": 2}


@dataclass(slots=True)
class LoadStats:
    telemetry_lines: int = 0
    telemetry_skipped: int = 0
    telemetry_duplicates: int = 0
    cost_lines: int = 0
    cost_skipped: int = 0
    cost_duplicates: int = 0


@dataclass(slots=True)
class _DayAcc:
    events: int = 0
    requests: int = 0
    errors: int = 0
    durations: list[int] | None = None
    cost: Decimal = Decimal(0)


def _lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield stripped


def _source_of(agent_id: str) -> str:
    parts = agent_id.split(":")
    return parts[2] if len(parts) >= 5 else ""


def _day_of(timestamp: str) -> date | None:
    try:
        return datetime.strptime(timestamp[:10], "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def _percentile(values: list[int], q: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation)."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return float(ordered[rank - 1])


def _json_object(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class SandboxSeriesSource:
    """Loads a sandbox output directory once; ``series`` then slices it per call."""

    def __init__(self, directory: Path) -> None:
        self.stats = LoadStats()
        self._agents: dict[str, dict[str, Any]] = {}
        self._owners: dict[str, str] = {}
        self._tele: dict[tuple[str, date], _DayAcc] = {}
        self._cost: dict[tuple[str, date], _DayAcc] = {}
        self._tele_cover: set[tuple[str, date]] = set()
        self._cost_cover: set[tuple[str, date]] = set()
        self._load_agents(directory / "agents.ndjson")
        self._load_owners(directory / "relations.ndjson")
        self._load_telemetry(directory / "telemetry.ndjson")
        self._load_cost(directory / "cost.ndjson")

    # -- loading -----------------------------------------------------------------------------

    def _load_agents(self, path: Path) -> None:
        for line in _lines(path):
            doc = _json_object(line)
            if doc is None:
                continue
            ident = doc.get("id")
            if not all(
                isinstance(doc.get(k), str) for k in ("id", "cloud", "customer_id", "domain_id")
            ):
                continue
            self._agents[str(ident)] = doc

    def _load_owners(self, path: Path) -> None:
        chosen: dict[str, tuple[int, str]] = {}
        for line in _lines(path):
            doc = _json_object(line)
            if doc is None or doc.get("relation_type") != "owned_by":
                continue
            subject, target = doc.get("source_id"), doc.get("target_id")
            if not isinstance(subject, str) or not isinstance(target, str):
                continue
            rank = (0 if doc.get("status") == "asserted" else 1, target)
            if subject not in chosen or rank < chosen[subject]:
                chosen[subject] = rank
        self._owners = {subject: rank[1] for subject, rank in chosen.items()}

    def _load_telemetry(self, path: Path) -> None:
        seen: set[str] = set()
        for line in _lines(path):
            self.stats.telemetry_lines += 1
            doc = _json_object(line)
            if doc is None:
                self.stats.telemetry_skipped += 1
                continue
            try:
                TelemetryEvent.model_validate(doc)
            except ValidationError:
                self.stats.telemetry_skipped += 1
                continue
            agent_id = doc.get("canonical_agent_id")
            day = _day_of(str(doc["event_time"]))
            if not isinstance(agent_id, str) or day is None:
                self.stats.telemetry_skipped += 1
                continue
            event_id = str(doc["event_id"])
            if event_id in seen:
                self.stats.telemetry_duplicates += 1
                continue
            seen.add(event_id)
            self._tele_cover.add((_source_of(agent_id), day))
            acc = self._tele.setdefault((agent_id, day), _DayAcc())
            acc.events += 1
            if doc.get("span_kind") == "request":
                acc.requests += 1
                if doc.get("outcome") in _ERROR_OUTCOMES:
                    acc.errors += 1
                duration = doc.get("duration_ms")
                if isinstance(duration, int) and not isinstance(duration, bool):
                    if acc.durations is None:
                        acc.durations = []
                    acc.durations.append(duration)

    def _load_cost(self, path: Path) -> None:
        best: dict[str, tuple[int, str, date, Decimal]] = {}
        for line in _lines(path):
            self.stats.cost_lines += 1
            doc = _json_object(line)
            if doc is None:
                self.stats.cost_skipped += 1
                continue
            try:
                CostRecord.model_validate(doc)
                amount = Decimal(str(doc["amount"]))
            except (ValidationError, InvalidOperation, KeyError):
                self.stats.cost_skipped += 1
                continue
            agent_id = doc.get("canonical_agent_id")
            stamp = doc.get("usage_start") or doc.get("recorded_at")
            day = _day_of(str(stamp))
            if not isinstance(agent_id, str) or day is None:
                self.stats.cost_skipped += 1
                continue
            key = str(doc["dedupe_key"])
            rank = _COST_PRIORITY.get(str(doc.get("observation_source")), 9)
            if key in best:
                self.stats.cost_duplicates += 1
                if rank >= best[key][0]:
                    continue
            best[key] = (rank, agent_id, day, amount)
        for _rank, agent_id, day, amount in best.values():
            self._cost_cover.add((_source_of(agent_id), day))
            self._cost.setdefault((agent_id, day), _DayAcc()).cost += amount

    # -- reading -----------------------------------------------------------------------------

    def observed_window(self) -> tuple[date, date] | None:
        """``[first, last + 1 day)`` over days with any valid telemetry, or None when empty."""
        days = {day for _, day in self._tele_cover}
        if not days:
            return None
        return min(days), max(days) + timedelta(days=1)

    def series(
        self,
        *,
        cloud: str,
        customer_id: str,
        domain_ids: frozenset[str],
        start: date,
        end: date,
    ) -> Iterable[AgentSeries]:
        span = [start + timedelta(days=i) for i in range((end - start).days)]
        for agent_id in sorted(self._agents):
            doc = self._agents[agent_id]
            if (
                doc["cloud"] != cloud
                or doc["customer_id"] != customer_id
                or doc["domain_id"] not in domain_ids
            ):
                continue
            source = _source_of(agent_id)
            days = tuple(self._day(agent_id, source, day) for day in span)
            created = doc.get("created_at")
            yield AgentSeries(
                agent_id=agent_id,
                cloud=cloud,
                customer_id=customer_id,
                domain_id=str(doc["domain_id"]),
                source=source,
                lifecycle_status=str(doc.get("lifecycle_status", "unknown")),
                created_on=_day_of(created) if isinstance(created, str) else None,
                owner_id=self._owners.get(agent_id),
                days=days,
            )

    def _day(self, agent_id: str, source: str, day: date) -> AgentDay:
        covered = (source, day) in self._tele_cover
        if not covered:
            return AgentDay(day=day, covered=False)
        acc = self._tele.get((agent_id, day))
        cost: Decimal | None = None
        if (source, day) in self._cost_cover:
            found = self._cost.get((agent_id, day))
            cost = found.cost if found is not None else Decimal(0)
        if acc is None:
            return AgentDay(
                day=day,
                covered=True,
                event_count=0,
                request_count=0,
                error_count=0,
                latency_p95_ms=None,
                cost_amount=cost,
            )
        return AgentDay(
            day=day,
            covered=True,
            event_count=acc.events,
            request_count=acc.requests,
            error_count=acc.errors,
            latency_p95_ms=_percentile(acc.durations, 0.95) if acc.durations else None,
            latency_p50_ms=_percentile(acc.durations, 0.5) if acc.durations else None,
            cost_amount=cost,
            durations_ms=bound_durations(acc.durations) if acc.durations else None,
        )
