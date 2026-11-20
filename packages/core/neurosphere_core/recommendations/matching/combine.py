"""Combine per-signal readings into one explainable score, and rank candidates.

Weights are renormalized over the observed signals, so an unobserved signal carries weight 0
and contributes nothing (it is neither a zero nor a penalty). ``score = sum(contributions)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchSignal

from .models import CombinedResult, SignalValue

__all__ = [
    "COLD_START_CAP",
    "COLD_START_FACTOR",
    "TELEMETRY_SIGNALS",
    "combine",
    "confidence_for",
    "rank_candidates",
]

TELEMETRY_SIGNALS: tuple[str, ...] = ("historical_success", "latency", "usage")
COLD_START_FACTOR = 0.7
COLD_START_CAP = 0.6
_NEUTRAL_MARGIN_FACTOR = 0.8
_MARGIN_FULL = 0.25
"""Margin to the next candidate at which the margin factor stops growing."""


def confidence_for(
    score: float, observed_share: float, margin: float | None, *, cold_start: bool
) -> float:
    """Relative confidence in 0-1 (not a probability).

    ``score * observed_share * margin_factor``; the margin factor runs from 0.6 (tied with the
    next candidate) to 1.0 (a margin of 0.25 or more) and is 0.8 when there is no next
    candidate to compare with. A cold-start candidate is scaled by 0.7 and capped at 0.6, so it
    is always below an otherwise equal candidate whose telemetry is observed.
    """
    if margin is None:
        factor = _NEUTRAL_MARGIN_FACTOR
    else:
        factor = 0.6 + 0.4 * min(1.0, max(0.0, margin) / _MARGIN_FULL)
    conf = min(1.0, max(0.0, score * observed_share * factor))
    if cold_start:
        conf = min(conf * COLD_START_FACTOR, COLD_START_CAP)
    return conf


def combine(
    signal_values: Iterable[SignalValue],
    weights: Mapping[str, float],
    *,
    margin: float | None = None,
) -> CombinedResult:
    """Combine signal readings (one per signal name; later duplicates replace earlier)."""
    by_name: dict[str, SignalValue] = {sv.signal: sv for sv in signal_values}
    for name in weights:
        by_name.setdefault(name, SignalValue(signal=name, value=None, detail_code="not_computed"))
    total_weight = sum(w for w in weights.values() if w > 0.0)
    observed_weight = sum(
        weights.get(name, 0.0)
        for name, sv in by_name.items()
        if sv.value is not None and weights.get(name, 0.0) > 0.0
    )
    contributions: list[AgentMatchSignal] = []
    unobserved: list[str] = []
    score = 0.0
    for name in sorted(by_name):
        sv = by_name[name]
        raw = max(0.0, weights.get(name, 0.0))
        if sv.value is None:
            unobserved.append(name)
            eff, contrib = 0.0, 0.0
        elif observed_weight > 0.0:
            eff = raw / observed_weight
            contrib = eff * sv.value
        else:
            eff, contrib = 0.0, 0.0
        score += contrib
        contributions.append(
            AgentMatchSignal.model_validate(
                {
                    "signal": name,
                    "value": sv.value,
                    "weight": min(1.0, eff),
                    "contribution": contrib,
                    "detail_code": sv.detail_code,
                }
            )
        )
    score = min(1.0, max(0.0, score))
    share = observed_weight / total_weight if total_weight > 0.0 else 0.0
    cold = all(n not in by_name or by_name[n].value is None for n in TELEMETRY_SIGNALS)
    return CombinedResult(
        score=score,
        contributions=tuple(contributions),
        signal_values=tuple(by_name[n] for n in sorted(by_name)),
        cold_start=cold,
        confidence=confidence_for(score, share, margin, cold_start=cold),
        unobserved=tuple(unobserved),
        observed_share=min(1.0, share),
    )


def rank_candidates(
    candidates: Sequence[tuple[str, CombinedResult]],
) -> list[tuple[str, CombinedResult]]:
    """Order best first (score descending, canonical id ascending on ties).

    Each result's confidence is recomputed with its margin to the next candidate (the last
    candidate has no next one and gets the neutral margin factor).
    """
    ordered = sorted(candidates, key=lambda c: (-c[1].score, c[0]))
    out: list[tuple[str, CombinedResult]] = []
    for i, (cid, res) in enumerate(ordered):
        margin = res.score - ordered[i + 1][1].score if i + 1 < len(ordered) else None
        conf = confidence_for(res.score, res.observed_share, margin, cold_start=res.cold_start)
        out.append((cid, res.model_copy(update={"confidence": conf})))
    return out
