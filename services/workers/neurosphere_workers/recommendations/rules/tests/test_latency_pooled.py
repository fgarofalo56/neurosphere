"""Pooled-window latency rule (PRP-15 item 7): sparse data, evidence floor, score bounds."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from neurosphere_workers.recommendations.rules import (
    DEFAULT_RULES,
    AgentDay,
    RuleResult,
    SandboxSeriesSource,
    evaluate_rules,
)
from neurosphere_workers.recommendations.rules.series import (
    MAX_DURATION_SAMPLES_PER_DAY,
    bound_durations,
)
from neurosphere_workers.recommendations.rules.tests.support import (
    CREATED_AT,
    REPO_ROOT,
    agent,
    contract_problems,
    day,
    make_scope,
)

Evaluate = Callable[..., list[RuleResult]]
OLD = date(2026, 3, 1)
FLOOR = DEFAULT_RULES.latency_degradation.min_window_requests


def _days(base: list[tuple[int, ...]], recent: list[tuple[int, ...]]) -> tuple[AgentDay, ...]:
    """7 covered days; per-day duration tuples for the 3 baseline and the 4 recent days."""
    out = []
    for i, durations in enumerate([*base, *recent]):
        out.append(
            day(
                i,
                event_count=max(1, 5 * len(durations)),
                request_count=len(durations),
                error_count=0,
                durations_ms=durations or None,
            )
        )
    return tuple(out)


def _latency(results: list[RuleResult]) -> RuleResult:
    (only,) = [r for r in results if r.rule_id == "latency_degradation"]
    return only


def test_rule_version_was_bumped() -> None:
    assert DEFAULT_RULES.latency_degradation.version == "2.0.0"


def test_pooled_window_detects_regression_no_single_day_has_a_statistic(evaluate: Evaluate) -> None:
    # 3 requests a day: the pooled windows hold 9 and 12 durations, enough for the floor of 8.
    base = [(100, 110, 120)] * 3
    recent = [(300, 320, 330)] * 4
    result = _latency(evaluate(agent("p-1", _days(base, recent), created_on=OLD)))
    assert result.outcome == "detected"
    rec = result.recommendation
    assert rec is not None and rec.score is not None
    assert rec.evidence_status == "sufficient"
    assert rec.generator is not None and rec.generator.generator_version.root == "2.0.0"
    assert rec.uncertainty.method == "rule_bound"
    assert rec.uncertainty.lower is not None and rec.uncertainty.upper is not None
    assert 0.0 <= rec.uncertainty.lower <= rec.score <= rec.uncertainty.upper <= 1.0
    assert result.threshold["baseline_requests"] == 9 and result.threshold["recent_requests"] == 12
    assert contract_problems(rec.model_dump(mode="json", exclude_unset=True)) == []


def test_unchanged_latency_is_not_detected(evaluate: Evaluate) -> None:
    base = [(100, 110, 120)] * 3
    recent = [(105, 112, 125)] * 4
    result = _latency(evaluate(agent("p-2", _days(base, recent), created_on=OLD)))
    assert result.outcome == "not_detected" and result.recommendation is None


@pytest.mark.parametrize(
    ("base", "recent"),
    [
        # a clear 3x regression, but only 4 recent requests: below the floor, never silent
        ([(100, 110)] * 3, [(300,)] * 4),
        # a clean sparse agent is also below the floor: the record is not a finding of degradation
        ([(100, 110)] * 3, [(100,)] * 4),
        # observations only in the recent window
        ([()] * 3, [(100, 120)] * 4),
    ],
)
def test_below_floor_is_insufficient_evidence_without_score(
    evaluate: Evaluate, base: list[tuple[int, ...]], recent: list[tuple[int, ...]]
) -> None:
    result = _latency(evaluate(agent("p-3", _days(base, recent), created_on=OLD)))
    assert result.outcome == "insufficient_evidence"
    rec = result.recommendation
    assert rec is not None
    assert rec.evidence_status == "insufficient_evidence"
    assert rec.score is None
    assert rec.uncertainty.method == "not_estimable"
    assert rec.uncertainty.lower is None and rec.uncertainty.upper is None
    doc = rec.model_dump(mode="json", exclude_unset=True)
    assert "score" not in doc
    assert contract_problems(doc) == []
    assert rec.coverage.method == "full"
    assert result.threshold["min_window_requests"] == FLOOR
    assert str(FLOOR) in result.threshold["statement"]
    assert rec.generator is not None and rec.generator.generator_version.root == "2.0.0"


def test_no_duration_observed_is_baseline_unavailable(evaluate: Evaluate) -> None:
    result = _latency(evaluate(agent("p-4", _days([()] * 3, [()] * 4), created_on=OLD)))
    assert result.outcome == "baseline_unavailable" and result.recommendation is None


def test_score_grows_with_ratio_and_stays_within_bounds(evaluate: Evaluate) -> None:
    scores = []
    for factor in (2.2, 3.0, 5.0):
        base = [tuple(100 + 5 * k for k in range(4))] * 3
        recent = [tuple(int((100 + 5 * k) * factor) for k in range(4))] * 4
        rec = _latency(evaluate(agent("p-5", _days(base, recent), created_on=OLD))).recommendation
        assert rec is not None and rec.score is not None
        assert rec.uncertainty.lower is not None and rec.uncertainty.upper is not None
        assert rec.uncertainty.lower <= rec.score <= rec.uncertainty.upper
        scores.append(rec.score)
    assert scores == sorted(scores) and scores[0] < scores[-1] and scores[-1] <= 1.0


def test_duration_sampling_is_bounded_deterministic_and_keeps_extremes() -> None:
    values = list(range(10_000, 0, -1))
    bounded = bound_durations(values)
    assert len(bounded) == MAX_DURATION_SAMPLES_PER_DAY
    assert bounded == bound_durations(reversed(values))
    assert bounded[0] == 1 and bounded[-1] == 10_000 and list(bounded) == sorted(bounded)
    assert bound_durations([5, 1, 3]) == (1, 3, 5)


@pytest.fixture(scope="module")
def sparse_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[RuleResult]]:
    """Pilot-like traffic density (about 2 traces per agent per day)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from sandbox.config import BadEventRates, GenerateConfig, Profile
    from sandbox.generate import generate

    out = tmp_path_factory.mktemp("sparse-latency")
    profile = Profile(
        "custom",
        domains=4,
        agents=80,
        days=7,
        traces_per_agent_day=2.0,
        cost_spikes=2,
        latency_regressions=4,
        unused_agents=2,
        duplicate_pairs=1,
    )
    generate(
        GenerateConfig(seed=3, profile=profile, cloud="commercial", rates=BadEventRates()), out
    )
    source = SandboxSeriesSource(out)
    window = source.observed_window()
    assert window is not None
    domains = tuple(
        json.loads(x)["id"]
        for x in (out / "domains.ndjson").read_text(encoding="utf-8").splitlines()
    )
    results = evaluate_rules(
        source,
        scope=make_scope(domains),
        window_start=window[0],
        window_end=window[1],
        created_at=CREATED_AT,
    )
    return out, results


def test_sparse_sandbox_never_silently_misses_an_injected_regression(
    sparse_run: tuple[Path, list[RuleResult]],
) -> None:
    out, results = sparse_run
    manifest = json.loads((out / "anomaly-manifest.json").read_text(encoding="utf-8"))
    injected = {
        i
        for a in manifest["anomalies"]
        if a["type"] == "latency_regression"
        for i in a["affected_ids"]
    }
    assert injected
    latency = {r.agent_id: r for r in results if r.rule_id == "latency_degradation"}
    for agent_id in injected:
        assert latency[agent_id].outcome in {"detected", "insufficient_evidence"}, agent_id
    for r in latency.values():
        if r.outcome == "insufficient_evidence":
            assert r.recommendation is not None and r.recommendation.score is None
        if r.recommendation is not None:
            assert (
                contract_problems(r.recommendation.model_dump(mode="json", exclude_unset=True))
                == []
            )
