"""Bounded rule evaluator emitting PRP-01 ``Recommendation`` records (PRP-15 item 1).

Pure and deterministic: no wall clock, no randomness, no network. ``created_at`` is passed in.
The evaluator is scoped by a server-derived ``IdentityScope`` (keyword-only): only agents of the
scope's cloud and customer in its allowed domains are read or evaluated.

Outcomes per (agent, rule), returned as ``RuleResult``:

* ``detected``: the rule fired; ``recommendation`` carries a rule-derived score (see config.py).
* ``not_detected``: evidence was sufficient and nothing breached; no record.
* ``insufficient_evidence``: cold start. History below the rule's minimum. A record is emitted
  with ``evidence_status=insufficient_evidence``, NO score and ``uncertainty.method=not_estimable``;
  ``RuleResult.threshold`` states the applicable minimum and what was observed.
* ``unknown_coverage``: telemetry coverage of the agent's source is unknown in the window. No
  record: unknown is never reported as unused or as zero.
* (latency) ``insufficient_evidence`` also covers a window holding fewer request durations than
  the rule's floor (``min_window_requests``): record without score, threshold and counts stated.
* ``baseline_unavailable``: enough history, but the baseline holds too few known values to compare
  against (for example no cost data). No record and no claim.
* ``no_activity`` (time-series rules, agent with zero events: ``unused_agent`` owns that case) and
  ``not_applicable`` (agent not active, or no relevant days) produce no record either.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.rules.config import (
    DEFAULT_RULES,
    CostSpikeConfig,
    ErrorRateConfig,
    LatencyDegradationConfig,
    RuleSet,
    UnusedAgentConfig,
)
from neurosphere_workers.recommendations.rules.series import (
    AgentDay,
    AgentSeries,
    AgentSeriesSource,
)

Outcome = Literal[
    "detected",
    "not_detected",
    "insufficient_evidence",
    "unknown_coverage",
    "baseline_unavailable",
    "no_activity",
    "not_applicable",
]
SCHEMA_VERSION = "1.0.0"
MAX_EVIDENCE_IDS = 200


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: str
    rule_version: str
    agent_id: str
    outcome: Outcome
    threshold: dict[str, Any] = field(default_factory=dict)
    breach_days: int | None = None
    recommendation: Recommendation | None = None


@dataclass(frozen=True, slots=True)
class _Prep:
    """One agent over one lookback range."""

    days: tuple[AgentDay, ...]  # relevant days only (on/after creation), oldest first
    covered: tuple[AgentDay, ...]
    start: date
    end: date

    @property
    def history_days(self) -> int:
        return len(self.covered)

    @property
    def active(self) -> bool:
        return any((d.event_count or 0) > 0 for d in self.covered)


def _ts(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _created_ts(created_at: datetime) -> str:
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        raise ValueError("created_at must be a timezone-aware UTC datetime")
    return created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def recommendation_id(
    *, cloud: str, customer_id: str, kind: str, generator_id: str, generator_version: str,
    subject_ids: Sequence[str], window_start: str, window_end: str,
) -> str:  # fmt: skip
    material = "|".join(
        [generator_id, generator_version, *sorted(subject_ids), window_start, window_end]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    slug = kind.replace("_", "-")
    return f"{cloud}:{customer_id}:neurosphere:recommendation:{slug}-{digest}"


def _prep(series: AgentSeries, start: date, end: date, lookback: int) -> _Prep | None:
    first = max(start, end - timedelta(days=lookback))
    by_day = {d.day: d for d in series.days}
    relevant: list[AgentDay] = []
    day = first
    while day < end:
        if series.created_on is None or day >= series.created_on:
            relevant.append(by_day.get(day) or AgentDay(day=day, covered=False))
        day += timedelta(days=1)
    if not relevant:
        return None
    covered = tuple(d for d in relevant if d.covered)
    return _Prep(days=tuple(relevant), covered=covered, start=first, end=end)


def _coverage(prep: _Prep) -> dict[str, Any]:
    if not prep.covered:
        return {"method": "unknown", "observed_fraction": None}
    fraction = len(prep.covered) / len(prep.days)
    return {"method": "full" if fraction == 1.0 else "partial", "observed_fraction": fraction}


def _owner(series: AgentSeries) -> dict[str, Any]:
    owner = series.owner_id
    if owner is not None:
        parts = owner.split(":")
        if len(parts) >= 2 and parts[0] == series.cloud and parts[1] == series.customer_id:
            return {"resolution": "assigned", "owner_id": owner}
    return {"resolution": "unresolved", "owner_id": None}


def _evidence_ids(series: AgentSeries, days: Sequence[AgentDay]) -> list[str]:
    ids = sorted({f"series:{series.agent_id}:{d.day.isoformat()}" for d in days})
    return ids[:MAX_EVIDENCE_IDS]


def _build(
    series: AgentSeries,
    *,
    kind: str,
    rule_id: str,
    rule_version: str,
    prep: _Prep,
    evidence_days: Sequence[AgentDay],
    score: float | None,
    bounds: tuple[float, float] | None,
    created_at: str,
) -> Recommendation:
    window = {"start": _ts(prep.start), "end": _ts(prep.end)}
    owner = _owner(series)
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "recommendation_id": recommendation_id(
            cloud=series.cloud,
            customer_id=series.customer_id,
            kind=kind,
            generator_id=rule_id,
            generator_version=rule_version,
            subject_ids=[series.agent_id],
            window_start=window["start"],
            window_end=window["end"],
        ),
        "cloud": series.cloud,
        "customer_id": series.customer_id,
        "domain_id": series.domain_id,
        "kind": kind,
        "subject_ids": [series.agent_id],
        "method": "rule",
        "generator": {"generator_id": rule_id, "generator_version": rule_version},
        "evidence_status": "insufficient_evidence" if score is None else "sufficient",
        "evidence_window": window,
        "evidence_ids": _evidence_ids(series, evidence_days),
        "coverage": _coverage(prep),
        "uncertainty": (
            {"method": "not_estimable"}
            if score is None or bounds is None
            else {"method": "rule_bound", "lower": bounds[0], "upper": bounds[1]}
        ),
        "prerequisites": [
            {"kind": "approval", "status": "unmet"},
            {
                "kind": "owner_consent",
                "status": "unknown" if owner["resolution"] == "assigned" else "unmet",
            },
            {"kind": "write_connector_available", "status": "unknown"},
        ],
        "owner": owner,
        "advisory": True,
        "created_at": created_at,
    }
    if score is not None:
        doc["score"] = score
    return Recommendation.model_validate(doc)


def _bound(count: int, denominator: int) -> tuple[float, float, float]:
    """Rule score and one-day-tolerance bound for ``count`` of ``denominator`` days."""
    score = min(count, denominator) / denominator
    lower = max(0, count - 1) / denominator
    upper = min(denominator, count + 1) / denominator
    return score, lower, upper


def _cold(
    series: AgentSeries,
    *,
    kind: str,
    rule_id: str,
    version: str,
    prep: _Prep,
    created_at: str,
    min_history: int,
) -> RuleResult:
    threshold = {
        "rule_id": rule_id,
        "rule_version": version,
        "min_history_days": min_history,
        "observed_history_days": prep.history_days,
        "statement": (
            f"{rule_id} needs {min_history} covered days of history; "
            f"{prep.history_days} observed. No score is produced below this threshold."
        ),
    }
    rec = _build(
        series,
        kind=kind,
        rule_id=rule_id,
        rule_version=version,
        prep=prep,
        evidence_days=prep.covered,
        score=None,
        bounds=None,
        created_at=created_at,
    )
    return RuleResult(
        rule_id, version, series.agent_id, "insufficient_evidence", threshold, None, rec
    )


def _eval_windowed(
    series: AgentSeries,
    cfg: CostSpikeConfig | ErrorRateConfig,
    window: tuple[date, date],
    created_at: str,
) -> RuleResult:
    rule_id, version = cfg.rule_id, cfg.version
    prep = _prep(series, window[0], window[1], cfg.lookback_days)

    def result(outcome: Outcome, **kw: Any) -> RuleResult:
        return RuleResult(rule_id, version, series.agent_id, outcome, **kw)

    if prep is None:
        return result("not_applicable")
    if not prep.covered:
        return result("unknown_coverage")
    if not prep.active:
        return result("no_activity")
    if prep.history_days < cfg.min_history_days:
        return _cold(
            series,
            kind=rule_id,
            rule_id=rule_id,
            version=version,
            prep=prep,
            created_at=created_at,
            min_history=cfg.min_history_days,
        )
    recent = [d for d in prep.days[-cfg.recent_window_days :] if d.covered]
    baseline = [
        d for d in prep.days[: -cfg.recent_window_days][-cfg.baseline_window_days :] if d.covered
    ]
    threshold: dict[str, Any] = cfg.model_dump(mode="json")
    breaches: list[AgentDay]
    if isinstance(cfg, CostSpikeConfig):
        base_costs = [d.cost_amount for d in baseline if d.cost_amount is not None]
        if len(base_costs) < cfg.min_baseline_known_days:
            return result("baseline_unavailable", threshold=threshold)
        median = statistics.median(base_costs)
        if median <= Decimal(0):
            return result("baseline_unavailable", threshold=threshold)
        limit = median * cfg.ratio
        breaches = [d for d in recent if d.cost_amount is not None and d.cost_amount > limit]
    else:
        base_requests = sum(d.request_count or 0 for d in baseline if d.error_count is not None)
        if base_requests < cfg.min_baseline_requests:
            return result("baseline_unavailable", threshold=threshold)
        base_rate = sum(d.error_count or 0 for d in baseline) / base_requests
        limit_rate = max(cfg.min_error_rate, cfg.ratio * base_rate)
        breaches = [
            d
            for d in recent
            if d.error_count is not None
            and (d.request_count or 0) >= cfg.min_requests_per_day
            and d.error_count / (d.request_count or 1) > limit_rate
        ]
    threshold["breach_days"] = len(breaches)
    if len(breaches) < cfg.min_breach_days:
        return result("not_detected", threshold=threshold, breach_days=len(breaches))
    score, lower, upper = _bound(len(breaches), cfg.recent_window_days)
    rec = _build(
        series,
        kind=rule_id,
        rule_id=rule_id,
        rule_version=version,
        prep=prep,
        evidence_days=breaches,
        score=score,
        bounds=(lower, upper),
        created_at=created_at,
    )
    return result("detected", threshold=threshold, breach_days=len(breaches), recommendation=rec)


def _rank_value(ordered: Sequence[int], q: float, shift: int = 0) -> int:
    """Nearest-rank order statistic of an ascending sequence, ``shift`` ranks up (clamped)."""
    index = max(1, math.ceil(q * len(ordered))) - 1 + shift
    return ordered[min(len(ordered) - 1, max(0, index))]


def _latency_score(ratio_observed: float, ratio: float) -> float:
    return min(1.0, max(0.0, (ratio_observed - 1.0) / (2.0 * (ratio - 1.0))))


def _eval_latency(
    series: AgentSeries,
    cfg: LatencyDegradationConfig,
    window: tuple[date, date],
    created_at: str,
) -> RuleResult:
    """Pooled-window latency rule (see ``LatencyDegradationConfig``)."""
    rule_id, version = cfg.rule_id, cfg.version
    prep = _prep(series, window[0], window[1], cfg.lookback_days)

    def result(outcome: Outcome, **kw: Any) -> RuleResult:
        return RuleResult(rule_id, version, series.agent_id, outcome, **kw)

    if prep is None:
        return result("not_applicable")
    if not prep.covered:
        return result("unknown_coverage")
    if not prep.active:
        return result("no_activity")
    if prep.history_days < cfg.min_history_days:
        return _cold(
            series,
            kind=rule_id,
            rule_id=rule_id,
            version=version,
            prep=prep,
            created_at=created_at,
            min_history=cfg.min_history_days,
        )
    recent_days = [d for d in prep.days[-cfg.recent_window_days :] if d.covered]
    base_days = [
        d for d in prep.days[: -cfg.recent_window_days][-cfg.baseline_window_days :] if d.covered
    ]
    base = sorted(x for d in base_days for x in (d.durations_ms or ()))
    recent = sorted(x for d in recent_days for x in (d.durations_ms or ()))
    q = 0.95 if cfg.percentile == "p95" else 0.5
    threshold: dict[str, Any] = cfg.model_dump(mode="json")
    threshold |= {"baseline_requests": len(base), "recent_requests": len(recent)}
    if not base and not recent:
        return result("baseline_unavailable", threshold=threshold)
    if min(len(base), len(recent)) < cfg.min_window_requests:
        threshold["statement"] = (
            f"{rule_id} needs {cfg.min_window_requests} request durations in each of the baseline "
            f"and recent windows; {len(base)} and {len(recent)} observed. No score is produced "
            "below this threshold."
        )
        rec = _build(
            series,
            kind=rule_id,
            rule_id=rule_id,
            rule_version=version,
            prep=prep,
            evidence_days=[d for d in (*base_days, *recent_days) if d.durations_ms],
            score=None,
            bounds=None,
            created_at=created_at,
        )
        return result("insufficient_evidence", threshold=threshold, recommendation=rec)
    base_stat, recent_stat = _rank_value(base, q), _rank_value(recent, q)
    if base_stat <= 0:
        return result("baseline_unavailable", threshold=threshold)
    observed = recent_stat / base_stat
    threshold["observed_ratio"] = round(observed, 4)
    evidence_days = [d for d in recent_days if d.durations_ms]
    if observed <= cfg.ratio:
        return result("not_detected", threshold=threshold)
    lower_ratio = _rank_value(recent, q, -1) / max(1, _rank_value(base, q, 1))
    upper_ratio = _rank_value(recent, q, 1) / max(1, _rank_value(base, q, -1))
    score = _latency_score(observed, cfg.ratio)
    rec = _build(
        series,
        kind=rule_id,
        rule_id=rule_id,
        rule_version=version,
        prep=prep,
        evidence_days=evidence_days,
        score=score,
        bounds=(min(score, _latency_score(lower_ratio, cfg.ratio)),
                max(score, _latency_score(upper_ratio, cfg.ratio))),
        created_at=created_at,
    )  # fmt: skip
    return result("detected", threshold=threshold, recommendation=rec)


def _eval_unused(
    series: AgentSeries,
    cfg: UnusedAgentConfig,
    window: tuple[date, date],
    created_at: str,
) -> RuleResult:
    rule_id, version = cfg.rule_id, cfg.version
    threshold: dict[str, Any] = cfg.model_dump(mode="json")

    def result(outcome: Outcome, **kw: Any) -> RuleResult:
        return RuleResult(rule_id, version, series.agent_id, outcome, **kw)

    if series.lifecycle_status != "active":
        return result("not_applicable")
    prep = _prep(series, window[0], window[1], cfg.window_days)
    if prep is None:
        return result("not_applicable")
    if not prep.covered:
        # No telemetry coverage for this source in the window: unknown, never "unused".
        return result("unknown_coverage", threshold=threshold)
    if prep.active:
        return result("not_detected", threshold=threshold)
    if prep.history_days < cfg.min_history_days:
        return _cold(
            series,
            kind=rule_id,
            rule_id=rule_id,
            version=version,
            prep=prep,
            created_at=created_at,
            min_history=cfg.min_history_days,
        )
    score, lower, upper = _bound(prep.history_days, cfg.full_confidence_days)
    rec = _build(
        series,
        kind=rule_id,
        rule_id=rule_id,
        rule_version=version,
        prep=prep,
        evidence_days=prep.covered,
        score=score,
        bounds=(lower, upper),
        created_at=created_at,
    )
    return result("detected", threshold=threshold, recommendation=rec)


def evaluate_rules(
    source: AgentSeriesSource,
    *,
    scope: IdentityScope,
    window_start: date,
    window_end: date,
    created_at: datetime,
    rules: RuleSet = DEFAULT_RULES,
) -> list[RuleResult]:
    """Evaluate every rule for every in-scope agent over ``[window_start, window_end)``.

    ``scope`` is the server-derived ``IdentityScope`` (keyword-only, never caller-supplied
    domain or customer ids). Results are ordered by agent id, then rule.
    """
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    stamp = _created_ts(created_at)
    allowed = frozenset(scope.allowed_domains)
    window = (window_start, window_end)
    results: list[RuleResult] = []
    for series in source.series(
        cloud=scope.cloud,
        customer_id=scope.customer_id,
        domain_ids=allowed,
        start=window_start,
        end=window_end,
    ):
        if (
            series.cloud != scope.cloud
            or series.customer_id != scope.customer_id
            or series.domain_id not in allowed
        ):
            continue
        results.append(_eval_windowed(series, rules.cost_spike, window, stamp))
        results.append(_eval_latency(series, rules.latency_degradation, window, stamp))
        results.append(_eval_windowed(series, rules.error_rate_degradation, window, stamp))
        results.append(_eval_unused(series, rules.unused_agent, window, stamp))
    return results


def recommendations(results: Sequence[RuleResult]) -> list[Recommendation]:
    """The emitted records (detections and cold-start results), in result order."""
    return [r.recommendation for r in results if r.recommendation is not None]
