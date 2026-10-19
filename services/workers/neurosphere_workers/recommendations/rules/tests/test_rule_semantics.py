"""Constructed-series tests: error-rate rule, score and id conventions, owner, scope, configs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from neurosphere_workers.recommendations.rules import (
    DEFAULT_RULES,
    CostSpikeConfig,
    RuleResult,
    evaluate_rules,
    recommendation_id,
)
from neurosphere_workers.recommendations.rules.tests.support import (
    CLOUD,
    CREATED_AT,
    CUSTOMER,
    DOMAIN,
    END,
    START,
    ListSource,
    agent,
    contract_problems,
    flat_days,
    make_scope,
)

Evaluate = Callable[..., list[RuleResult]]
OLD = date(2026, 3, 1)
OWNER = f"{CLOUD}:{CUSTOMER}:sandbox:owner:o-1"


def _by_rule(results: list[RuleResult]) -> dict[str, RuleResult]:
    return {r.rule_id: r for r in results}


def test_error_rate_degradation_detected_on_constructed_series(evaluate: Evaluate) -> None:
    # No errors in the baseline window, 5 of 10 requests failing on every recent day.
    days = flat_days(patch={i: {"error_count": 5} for i in range(3, 7)})
    result = _by_rule(evaluate(agent("err-1", days, created_on=OLD, owner_id=OWNER)))[
        "error_rate_degradation"
    ]
    assert result.outcome == "detected"
    rec = result.recommendation
    assert rec is not None
    assert rec.kind == "error_rate_degradation"
    assert rec.score == 1.0  # 4 of 4 recent days breach
    assert rec.uncertainty.method == "rule_bound"
    assert rec.uncertainty.lower == 0.75 and rec.uncertainty.upper == 1.0
    assert contract_problems(rec.model_dump(mode="json", exclude_unset=True)) == []


def test_error_rate_not_detected_when_baseline_already_high(evaluate: Evaluate) -> None:
    days = flat_days(errors=5)  # 50% errors throughout: not a degradation
    result = _by_rule(evaluate(agent("err-2", days, created_on=OLD)))["error_rate_degradation"]
    assert result.outcome == "not_detected"
    assert result.recommendation is None


def test_cost_spike_and_latency_on_constructed_series(evaluate: Evaluate) -> None:
    patch = {
        i: {"cost_amount": Decimal("40"), "latency_p50_ms": 150.0, "latency_p95_ms": 400.0}
        for i in (4, 5)
    }
    patch |= {6: {"latency_p50_ms": 150.0}, 3: {"latency_p50_ms": 150.0}}
    results = _by_rule(evaluate(agent("mix-1", flat_days(patch=patch), created_on=OLD)))
    cost = results["cost_spike"]
    assert cost.outcome == "detected" and cost.breach_days == 2
    assert cost.recommendation is not None
    assert cost.recommendation.score == 0.5  # 2 of 4 recent days
    assert results["latency_degradation"].outcome == "detected"
    assert results["error_rate_degradation"].outcome == "not_detected"


def test_single_breach_day_is_below_min_breach_days(evaluate: Evaluate) -> None:
    days = flat_days(patch={5: {"cost_amount": Decimal("500")}})
    assert _by_rule(evaluate(agent("one-1", days, created_on=OLD)))["cost_spike"].outcome == (
        "not_detected"
    )


def test_score_always_within_rule_bound(evaluate: Evaluate) -> None:
    for breaching in range(2, 5):
        patch = {7 - 1 - i: {"cost_amount": Decimal("99")} for i in range(breaching)}
        result = _by_rule(evaluate(agent("b-1", flat_days(patch=patch), created_on=OLD)))[
            "cost_spike"
        ]
        rec = result.recommendation
        assert rec is not None and rec.score is not None
        assert rec.uncertainty.lower is not None and rec.uncertainty.upper is not None
        assert rec.uncertainty.lower <= rec.score <= rec.uncertainty.upper
        assert rec.score == breaching / 4


def test_recommendation_id_convention_and_pattern(evaluate: Evaluate) -> None:
    result = _by_rule(evaluate(agent("id-1", flat_days(events=0, requests=0), created_on=OLD)))[
        "unused_agent"
    ]
    rec = result.recommendation
    assert rec is not None
    subject = f"{CLOUD}:{CUSTOMER}:sandbox:agent:id-1"
    material = "|".join(
        ["unused_agent", "1.0.0", subject, "2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"]
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:24]
    expected = f"{CLOUD}:{CUSTOMER}:neurosphere:recommendation:unused-agent-{digest}"
    assert rec.recommendation_id.root == expected
    assert contract_problems(rec.model_dump(mode="json", exclude_unset=True)) == []
    assert recommendation_id(
        cloud=CLOUD,
        customer_id=CUSTOMER,
        kind="cost_spike",
        generator_id="cost_spike",
        generator_version="1.0.0",
        subject_ids=[subject],
        window_start="a",
        window_end="b",
    ).startswith(f"{CLOUD}:{CUSTOMER}:neurosphere:recommendation:cost-spike-")


def test_owner_resolution_and_consent_prerequisite(evaluate: Evaluate) -> None:
    idle = flat_days(events=0, requests=0)
    owned = _by_rule(evaluate(agent("o-1", idle, created_on=OLD, owner_id=OWNER)))["unused_agent"]
    orphan = _by_rule(evaluate(agent("o-2", idle, created_on=OLD)))["unused_agent"]
    foreign = _by_rule(
        evaluate(agent("o-3", idle, created_on=OLD, owner_id="government:synthco:x:owner:o-9"))
    )["unused_agent"]
    assert owned.recommendation is not None
    assert owned.recommendation.owner.resolution == "assigned"
    assert owned.recommendation.owner.owner_id is not None
    assert owned.recommendation.owner.owner_id.root == OWNER
    for unresolved in (orphan, foreign):
        assert unresolved.recommendation is not None
        owner = unresolved.recommendation.owner
        assert owner.resolution == "unresolved" and owner.owner_id is None
        doc = unresolved.recommendation.model_dump(mode="json", exclude_unset=True)
        assert doc["owner"] == {"resolution": "unresolved", "owner_id": None}
        assert contract_problems(doc) == []
    kinds = {p.kind: p.status for p in owned.recommendation.prerequisites}
    assert kinds["approval"] == "unmet" and kinds["owner_consent"] == "unknown"


def test_deprecated_agent_is_never_unused(evaluate: Evaluate) -> None:
    idle = flat_days(events=0, requests=0)
    result = _by_rule(evaluate(agent("dep-1", idle, created_on=OLD, status="deprecated")))
    assert result["unused_agent"].outcome == "not_applicable"


def test_scope_filters_domain_customer_and_cloud() -> None:
    idle = flat_days(events=0, requests=0)
    mine = agent("s-1", idle, created_on=OLD)
    other_domain = agent(
        "s-2", idle, created_on=OLD, domain=f"{CLOUD}:{CUSTOMER}:sandbox:domain:dom-999"
    )
    source = ListSource(mine, other_domain)

    def ids(scope_domains: tuple[str, ...]) -> set[str]:
        results = evaluate_rules(
            source,
            scope=make_scope(scope_domains),
            window_start=START,
            window_end=END,
            created_at=CREATED_AT,
        )
        return {r.agent_id for r in results}

    assert ids((DOMAIN,)) == {mine.agent_id}
    assert ids(()) == set()


def test_window_and_created_at_validation() -> None:
    source = ListSource()
    with pytest.raises(ValueError, match="window_end"):
        evaluate_rules(
            source, scope=make_scope(), window_start=END, window_end=START, created_at=CREATED_AT
        )
    with pytest.raises(ValueError, match="UTC"):
        evaluate_rules(
            source,
            scope=make_scope(),
            window_start=START,
            window_end=END,
            created_at=datetime(2026, 10, 19, 12, 0, 0),
        )


def test_evidence_ids_are_bounded_and_unique(evaluate: Evaluate) -> None:
    long_end = START + timedelta(days=400)
    n = 400
    idle = tuple(flat_days(n, events=0, requests=0, errors=0, p95=None, p50=None, cost="0"))
    result = _by_rule(evaluate(agent("long-1", idle, created_on=OLD), end=long_end))["unused_agent"]
    # Only the last window_days (7) are examined; ids stay small and unique either way.
    assert result.recommendation is not None
    ids = [i.root for i in result.recommendation.evidence_ids]
    assert len(ids) == len(set(ids)) <= 200


def test_rule_configs_are_frozen_strict_and_versioned() -> None:
    cfg = DEFAULT_RULES.cost_spike
    assert cfg.rule_id == "cost_spike" and cfg.version == "1.0.0"
    with pytest.raises(ValidationError):
        cfg.version = "2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CostSpikeConfig.model_validate({**cfg.model_dump(), "surprise": 1})
    with pytest.raises(ValidationError):
        CostSpikeConfig.model_validate({**cfg.model_dump(), "min_history_days": 3})
    for rule in (DEFAULT_RULES.latency_degradation, DEFAULT_RULES.error_rate_degradation):
        assert rule.version and rule.min_history_days >= rule.recent_window_days
