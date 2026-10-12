"""Deliberately bad telemetry: duplicates, out-of-order, malformed, missing optional fields.

Defects are mutually exclusive per event and drawn from a dedicated seeded stream, so the mix
is reproducible. Every defect is reported to ``sink`` with the 1-based line number it landed
on in ``telemetry.ndjson``; that is the bad-event manifest PRP-07 asserts quarantine counts
against.
"""

from __future__ import annotations

import copy
import heapq
from collections import Counter
from collections.abc import Callable, Iterator
from typing import Any

from sandbox.config import BadEventRates
from sandbox.ids import rng_for
from sandbox.output import dumps

Doc = dict[str, Any]

OPTIONAL_DROPPABLE = (
    "parent_span_id",
    "model",
    "model_version",
    "provider",
    "duration_ms",
    "token_breakdown",
    "data_source_refs",
    "sampling",
    "request_id",
    "external_agent_id",
)
MALFORMED_MUTATIONS = (
    "missing_required_field",
    "invalid_trace_id",
    "negative_duration",
    "non_utc_timestamp",
    "unknown_field",
    "wrong_type",
)


def _malform(doc: Doc, mutation: str) -> Doc:
    bad = copy.deepcopy(doc)
    if mutation == "missing_required_field":
        bad.pop("cloud", None)
    elif mutation == "invalid_trace_id":
        bad["trace_id"] = "not-a-trace-id"
    elif mutation == "negative_duration":
        bad["duration_ms"] = -5
    elif mutation == "non_utc_timestamp":
        bad["event_time"] = "2026-10-01T10:00:00+02:00"
    elif mutation == "unknown_field":
        bad["unexpected_field"] = True
    else:  # wrong_type
        bad["duration_ms"] = "slow"
    return bad


class BadEventInjector:
    def __init__(self, seed: int, rates: BadEventRates, sink: Callable[[Doc], None]) -> None:
        self.rates = rates
        self.sink = sink
        self.rng = rng_for(seed, "bad-events")
        self.line = 0
        self.counts: Counter[str] = Counter()
        self._pending: list[tuple[int, int, bytes, Doc]] = []
        self._order = 0

    def _emit(self, payload: bytes, entry: Doc | None) -> bytes:
        self.line += 1
        if entry is not None:
            self.counts[entry["kind"]] += 1
            self.sink({"line": self.line, **entry})
        return payload

    def _defer(self, release_ms: int, payload: bytes, entry: Doc) -> None:
        self._order += 1
        heapq.heappush(self._pending, (release_ms, self._order, payload, entry))

    def _release(self, upto_ms: int | None) -> Iterator[bytes]:
        while self._pending and (upto_ms is None or self._pending[0][0] <= upto_ms):
            _, _, payload, entry = heapq.heappop(self._pending)
            yield self._emit(payload, entry)

    def feed(self, t_ms: int, doc: Doc) -> Iterator[bytes]:
        """Yield the output line(s) for one in-order event."""
        yield from self._release(t_ms)
        r = self.rng.random()
        rates = self.rates
        event_id = doc["event_id"]
        payload = dumps(doc)
        if r < rates.duplicate:
            first = self.line + 1
            yield self._emit(payload, None)
            delay = self.rng.randint(1, 60)
            self._defer(
                t_ms + delay * 1000,
                payload,
                {"kind": "duplicate", "event_id": event_id, "duplicate_of_line": first},
            )
            return
        r -= rates.duplicate
        if r < rates.out_of_order:
            delay = self.rng.randint(rates.late_min_seconds, rates.late_max_seconds)
            self._defer(
                t_ms + delay * 1000,
                payload,
                {
                    "kind": "out_of_order",
                    "event_id": event_id,
                    "event_time": doc["event_time"],
                    "delay_seconds": delay,
                },
            )
            return
        r -= rates.out_of_order
        if r < rates.malformed:
            mutation = self.rng.choice(MALFORMED_MUTATIONS)
            yield self._emit(
                dumps(_malform(doc, mutation)),
                {"kind": "malformed", "event_id": event_id, "mutation": mutation},
            )
            return
        r -= rates.malformed
        if r < rates.missing_optional:
            # The schema makes parent_span_id conditionally required for these span kinds.
            keep_parent = doc.get("span_kind") in {"delegation", "tool_call"}
            present = [
                f
                for f in OPTIONAL_DROPPABLE
                if f in doc and not (keep_parent and f == "parent_span_id")
            ]
            n = min(len(present), self.rng.randint(1, 3))
            dropped = sorted(self.rng.sample(present, n))
            slim = {k: v for k, v in doc.items() if k not in dropped}
            yield self._emit(
                dumps(slim),
                {"kind": "missing_optional", "event_id": event_id, "dropped_fields": dropped},
            )
            return
        yield self._emit(payload, None)

    def flush(self) -> Iterator[bytes]:
        """Release anything still held back (end of stream)."""
        yield from self._release(None)
