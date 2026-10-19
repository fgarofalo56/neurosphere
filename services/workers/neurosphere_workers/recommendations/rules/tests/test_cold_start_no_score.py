"""Cold start: below the minimum history the output is a bounded rule result with no score."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest

from neurosphere_workers.recommendations.rules import AgentSeries, RuleResult, recommendations
from neurosphere_workers.recommendations.rules.tests.conftest import SandboxRun
from neurosphere_workers.recommendations.rules.tests.support import (
    START,
    agent,
    contract_problems,
    day,
    flat_days,
)

Evaluate = Callable[..., list[RuleResult]]


def _new_agent() -> AgentSeries:
    """Created on day 4 of the 7-day window: 3 covered days of history, below the minimum 7."""
    days = tuple(
        day(
            i,
            event_count=10,
            request_count=10,
            error_count=0,
            latency_p95_ms=100.0,
            latency_p50_ms=50.0,
        )
        for i in range(4, 7)
    )
    return agent("new-1", days, created_on=START + timedelta(days=4))


@pytest.mark.parametrize("rule_id", ["cost_spike", "latency_degradation", "error_rate_degradation"])
def test_short_history_yields_insufficient_evidence_without_score(
    evaluate: Evaluate, rule_id: str
) -> None:
    results = [r for r in evaluate(_new_agent()) if r.rule_id == rule_id]
    assert len(results) == 1
    result = results[0]
    assert result.outcome == "insufficient_evidence"
    rec = result.recommendation
    assert rec is not None
    assert rec.method == "rule"
    assert rec.evidence_status == "insufficient_evidence"
    assert rec.score is None
    assert rec.uncertainty.method == "not_estimable"
    assert rec.uncertainty.lower is None and rec.uncertainty.upper is None
    doc = rec.model_dump(mode="json", exclude_unset=True)
    assert "score" not in doc
    assert contract_problems(doc) == []
    # The result states the threshold that applies, and what was observed against it.
    assert result.threshold["min_history_days"] == 7
    assert result.threshold["observed_history_days"] == 3
    assert "7" in result.threshold["statement"]
    assert rec.generator is not None
    assert rec.generator.generator_id.root == rule_id


def test_idle_new_agent_is_cold_start_for_unused_agent(evaluate: Evaluate) -> None:
    days = tuple(day(i, event_count=0, request_count=0, error_count=0) for i in range(4, 7))
    fresh = agent("idle-new", days, created_on=START + timedelta(days=4))
    result = next(r for r in evaluate(fresh) if r.rule_id == "unused_agent")
    assert result.outcome == "insufficient_evidence"
    assert result.recommendation is not None
    assert result.recommendation.score is None
    assert result.threshold["min_history_days"] == 7


def test_enough_history_is_not_cold_start(evaluate: Evaluate) -> None:
    results = evaluate(agent("old-1", flat_days(), created_on=date(2026, 3, 1)))
    assert all(r.outcome != "insufficient_evidence" for r in results)


def test_no_score_exactly_when_insufficient_evidence_in_sandbox(sandbox_run: SandboxRun) -> None:
    for rec in recommendations(sandbox_run.results):
        assert (rec.score is None) == (rec.evidence_status == "insufficient_evidence")
        assert (rec.uncertainty.method == "not_estimable") == (rec.score is None)
