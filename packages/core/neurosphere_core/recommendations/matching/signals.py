"""Pure per-candidate signal functions. No I/O: callers pass in already-fetched, in-scope data.

Every function returns ``SignalValue`` objects whose ``value`` is None when the signal could
not be observed. Unknown is never turned into 0.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from statistics import median

from neurosphere_core.aggregates.models import SubjectPoint

from .models import ProximityPath, SignalValue
from .tokens import normalize_tokens

__all__ = [
    "USAGE_SATURATION",
    "latency_pool_median",
    "lexical_signal",
    "proximity_signal",
    "tag_signal",
    "telemetry_signal",
]

USAGE_SATURATION = 10_000
"""``event_count`` at which the log-scaled usage signal reaches 1."""


def _unobserved(signal: str, detail: str) -> SignalValue:
    return SignalValue(signal=signal, value=None, detail_code=detail)


def _match_one(
    signal: str,
    candidate_items: Iterable[str],
    requested: Sequence[str],
    *,
    empty_detail: str,
) -> SignalValue:
    """Mean over requested items: exact normalized match is 1, else token overlap fraction."""
    if not requested:
        return _unobserved(signal, empty_detail)
    cand_sets = [normalize_tokens(c) for c in candidate_items]
    cand_exact = {c for c in cand_sets if c}
    cand_all = {t for c in cand_sets for t in c}
    total = 0.0
    counted = 0
    matched: list[str] = []
    for item in requested:
        toks = normalize_tokens(item)
        if not toks:
            continue
        counted += 1
        if toks in cand_exact:
            total += 1.0
            matched.append(item)
            continue
        frac = sum(1 for t in toks if t in cand_all) / len(toks)
        total += frac
        if frac > 0.0:
            matched.append(item)
    if counted == 0:
        return _unobserved(signal, empty_detail)
    return SignalValue(
        signal=signal,
        value=min(1.0, max(0.0, total / counted)),
        detail_code="matched" if matched else "no_match",
        matched=tuple(matched),
    )


def tag_signal(
    candidate_tags: Iterable[str],
    candidate_capabilities: Iterable[str],
    required_capabilities: Sequence[str],
    preferred_tags: Sequence[str],
) -> tuple[SignalValue, SignalValue]:
    """Return ``(capability_match, tag_match)``; each is unobserved when the request names none."""
    cap = _match_one(
        "capability_match",
        candidate_capabilities,
        required_capabilities,
        empty_detail="no_required_capabilities",
    )
    tag = _match_one("tag_match", candidate_tags, preferred_tags, empty_detail="no_preferred_tags")
    return cap, tag


def lexical_signal(entity_id: str, hit_scores: Mapping[str, float] | None) -> SignalValue:
    """``text_match``: the entity's search score over the top hit's score.

    ``hit_scores`` maps entity id to the score returned by an ``AuthorizedSearch`` result, or
    is None when search was not run or failed (the signal is then unobserved). An entity that
    search did not return is an observed 0.
    """
    if hit_scores is None:
        return _unobserved("text_match", "search_unavailable")
    top = max(hit_scores.values(), default=0.0)
    score = hit_scores.get(entity_id)
    if score is None or top <= 0.0 or score <= 0.0:
        return SignalValue(signal="text_match", value=0.0, detail_code="no_text_hit")
    return SignalValue(signal="text_match", value=min(1.0, score / top), detail_code="text_hit")


def latency_pool_median(points: Iterable[SubjectPoint | None]) -> float | None:
    """Median ``p95_ms`` over the candidates that have one; None when none do."""
    values = [p.p95_ms for p in points if p is not None and p.p95_ms is not None]
    return float(median(values)) if values else None


def telemetry_signal(
    point: SubjectPoint | None, pool_median_p95_ms: float | None
) -> tuple[SignalValue, SignalValue, SignalValue]:
    """Return ``(historical_success, latency, usage)``; each part is None when unknown.

    success = 1 - error_rate (an unknown error rate leaves it unobserved, never 1 and never 0
    errors); latency = median / (median + p95), 0.5 at the pool median and falling as p95
    grows; usage = log-scaled ``event_count`` saturating at ``USAGE_SATURATION``.
    """
    if point is None:
        return (
            _unobserved("historical_success", "no_telemetry"),
            _unobserved("latency", "no_telemetry"),
            _unobserved("usage", "no_telemetry"),
        )
    if point.error_rate is None:
        success = _unobserved("historical_success", "error_rate_unknown")
    else:
        success = SignalValue(
            signal="historical_success",
            value=min(1.0, max(0.0, 1.0 - point.error_rate)),
            detail_code="observed",
        )
    if point.p95_ms is None or pool_median_p95_ms is None:
        latency = _unobserved("latency", "latency_unknown")
    else:
        denom = pool_median_p95_ms + float(point.p95_ms)
        lat = 1.0 if denom <= 0.0 else pool_median_p95_ms / denom
        latency = SignalValue(
            signal="latency", value=min(1.0, max(0.0, lat)), detail_code="observed"
        )
    usage = SignalValue(
        signal="usage",
        value=min(1.0, math.log1p(max(0, point.event_count)) / math.log1p(USAGE_SATURATION)),
        detail_code="observed",
    )
    return success, latency, usage


def proximity_signal(paths: Sequence[ProximityPath] | None, max_hops: int = 2) -> SignalValue:
    """``graph_proximity`` from pre-computed bounded walk results for one candidate.

    ``paths`` is None when the request had no context entities (unobserved). Otherwise the
    best path within ``max_hops`` (at most 2 scores) wins: 0 or 1 hop scores 1, 2 hops 0.5. The
    winning edge type and hop count are kept for the explanation; no path is an observed 0.
    """
    if paths is None:
        return _unobserved("graph_proximity", "no_context_entities")
    limit = min(max_hops, 2)
    within = [p for p in paths if p.hops <= limit]
    if not within:
        return SignalValue(signal="graph_proximity", value=0.0, detail_code="no_path")
    best = min(within, key=lambda p: (p.hops, p.edge_type))
    value = 1.0 if best.hops <= 1 else 1.0 / best.hops
    return SignalValue(
        signal="graph_proximity",
        value=value,
        detail_code=f"hops_{best.hops}",
        edge_type=best.edge_type,
        hops=best.hops,
    )
