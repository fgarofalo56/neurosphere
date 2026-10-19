"""Missing telemetry is unknown coverage, never zero usage and never "unused"."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from neurosphere_workers.recommendations.rules import (
    AgentDay,
    RuleResult,
    SandboxSeriesSource,
    evaluate_rules,
    recommendations,
)
from neurosphere_workers.recommendations.rules.tests.conftest import SandboxRun
from neurosphere_workers.recommendations.rules.tests.support import (
    CREATED_AT,
    END,
    START,
    agent,
    contract_problems,
    day,
    flat_days,
    make_scope,
)

Evaluate = Callable[..., list[RuleResult]]


def _uncovered(n: int = 7) -> tuple[AgentDay, ...]:
    return tuple(day(i, covered=False) for i in range(n))


def test_source_without_telemetry_is_unknown_not_unused(evaluate: Evaluate) -> None:
    blind = agent("blind-1", _uncovered(), source="otherplat")
    results = evaluate(blind)
    assert {r.rule_id: r.outcome for r in results}["unused_agent"] == "unknown_coverage"
    assert recommendations(results) == []


def test_covered_source_with_zero_events_is_unused(evaluate: Evaluate) -> None:
    idle = agent(
        "idle-1", flat_days(events=0, requests=0, errors=0, p95=None, cost="0"), source="sandbox"
    )
    results = evaluate(idle)
    unused = next(r for r in results if r.rule_id == "unused_agent")
    assert unused.outcome == "detected"
    rec = unused.recommendation
    assert rec is not None
    assert rec.kind == "unused_agent"
    assert rec.coverage.method == "full"
    assert rec.coverage.observed_fraction is not None
    assert rec.coverage.observed_fraction.root == 1.0
    assert contract_problems(rec.model_dump(mode="json", exclude_unset=True)) == []


def test_unknown_coverage_record_shape_when_some_days_unseen(evaluate: Evaluate) -> None:
    """Partial coverage is stated as partial, with a fraction, not as zero usage."""
    days = tuple(
        day(i, event_count=0, request_count=0, error_count=0) if i != 5 else day(i, covered=False)
        for i in range(7)
    )
    results = evaluate(agent("gap-1", days, created_on=date(2026, 3, 1)))
    unused = next(r for r in results if r.rule_id == "unused_agent")
    # 6 covered days is below the 7-day minimum: cold start, no score, partial coverage.
    assert unused.outcome == "insufficient_evidence"
    assert unused.recommendation is not None
    cov = unused.recommendation.coverage
    assert cov.method == "partial" and cov.observed_fraction is not None
    assert abs(cov.observed_fraction.root - 6 / 7) < 1e-9


def test_unknown_values_stay_null_not_zero(evaluate: Evaluate) -> None:
    unseen = agent("unseen-1", _uncovered())
    for result in evaluate(unseen):
        assert result.outcome == "unknown_coverage" or result.outcome == "not_applicable"
    blind_day = day(0, covered=False)
    assert blind_day.event_count is None and blind_day.cost_amount is None


def test_unknown_cost_is_not_a_zero_baseline(evaluate: Evaluate) -> None:
    """Cost unknown on every baseline day: no baseline, no claim (not 'cost was zero')."""
    days = flat_days(cost=None, patch={4: {"cost_amount": Decimal("500")}})
    results = evaluate(agent("nocost-1", days, created_on=date(2026, 3, 1)))
    cost = next(r for r in results if r.rule_id == "cost_spike")
    assert cost.outcome == "baseline_unavailable"
    assert cost.recommendation is None


def _copy_with_extra_blind_agent(src: Path, dst: Path) -> str:
    shutil.copytree(src, dst)
    lines = (dst / "agents.ndjson").read_text(encoding="utf-8").splitlines()
    template = json.loads(lines[0])
    blind_id = "commercial:synthco:otherplat:agent:blind-9"
    template["id"] = blind_id
    template["lifecycle_status"] = "active"
    lines.append(json.dumps(template, sort_keys=True))
    (dst / "agents.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return blind_id


def test_sandbox_agent_from_uncovered_source_is_unknown(
    sandbox_run: SandboxRun, tmp_path: Path
) -> None:
    blind_id = _copy_with_extra_blind_agent(sandbox_run.directory, tmp_path / "copy")
    source = SandboxSeriesSource(tmp_path / "copy")
    window = source.observed_window()
    assert window is not None
    results = evaluate_rules(
        source,
        scope=make_scope(tuple(sandbox_run.domains)),
        window_start=window[0],
        window_end=window[1],
        created_at=CREATED_AT,
    )
    mine = [r for r in results if r.agent_id == blind_id]
    assert {r.rule_id: r.outcome for r in mine}["unused_agent"] == "unknown_coverage"
    assert all(r.recommendation is None for r in mine)
    series = next(
        s
        for s in source.series(
            cloud="commercial",
            customer_id="synthco",
            domain_ids=frozenset(sandbox_run.domains),
            start=window[0],
            end=window[1],
        )
        if s.agent_id == blind_id
    )
    assert all(d.covered is False and d.event_count is None for d in series.days)
    assert all(d.cost_amount is None for d in series.days)


def test_constants_cover_the_support_window() -> None:
    assert (END - START).days == 7
