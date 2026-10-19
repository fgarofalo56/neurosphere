"""Every injected sandbox anomaly is detected, with no false positives on the clean control set."""

from __future__ import annotations

import json
import re

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.rules import evaluate_rules, recommendations
from neurosphere_workers.recommendations.rules.tests.conftest import SandboxRun
from neurosphere_workers.recommendations.rules.tests.support import (
    CREATED_AT,
    contract_problems,
    make_scope,
)

CANONICAL_ID = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)


def _all_anomalous(run: SandboxRun) -> set[str]:
    kinds = ("cost_spike", "latency_regression", "unused_agent")
    return set().union(*(run.anomalies(k) for k in kinds))


def _agents_with_events(run: SandboxRun) -> set[str]:
    seen: set[str] = set()
    for line in (run.directory / "telemetry.ndjson").read_text(encoding="utf-8").splitlines():
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("canonical_agent_id"), str):
            seen.add(doc["canonical_agent_id"])
    return seen


def test_cost_spikes_all_detected_no_false_positives(sandbox_run: SandboxRun) -> None:
    expected = sandbox_run.anomalies("cost_spike")
    assert expected
    assert sandbox_run.detected("cost_spike") == expected


def test_latency_regressions_all_detected(sandbox_run: SandboxRun) -> None:
    expected = sandbox_run.anomalies("latency_regression")
    assert expected
    detected = sandbox_run.detected("latency_degradation")
    assert expected <= detected
    # The sandbox's cost spike multiplies tokens 12x, which genuinely lengthens those agents'
    # durations, so they may also (correctly) trip the latency rule. Nothing else may.
    assert detected - expected <= sandbox_run.anomalies("cost_spike")


def test_unused_agents_all_detected(sandbox_run: SandboxRun) -> None:
    expected = sandbox_run.anomalies("unused_agent")
    assert expected
    detected = sandbox_run.detected("unused_agent")
    assert expected <= detected
    # Any extra detection must be an active agent with no event at all in the raw telemetry
    # (generated sub-agents can be naturally idle); never an agent that has events.
    assert not (detected - expected) & _agents_with_events(sandbox_run)


def test_clean_control_set_has_no_detections(sandbox_run: SandboxRun) -> None:
    clean = {
        r.agent_id for r in sandbox_run.results if r.agent_id not in _all_anomalous(sandbox_run)
    }
    assert clean
    idle = clean - _agents_with_events(sandbox_run)
    for rule_id in ("cost_spike", "latency_degradation", "error_rate_degradation", "unused_agent"):
        false_positives = (sandbox_run.detected(rule_id) & clean) - idle
        assert not false_positives, (rule_id, sorted(false_positives))


def test_bad_events_are_deduped_and_skipped_not_fatal(sandbox_run: SandboxRun) -> None:
    expected = json.loads(
        (sandbox_run.directory / "bad-event-manifest.json").read_text(encoding="utf-8")
    )["expected"]
    stats = sandbox_run.source.stats
    assert stats.telemetry_lines == expected["total_lines"]
    assert stats.telemetry_skipped == expected["malformed_lines"]
    assert stats.telemetry_duplicates == expected["duplicate_lines"]
    distinct = stats.telemetry_lines - stats.telemetry_skipped - stats.telemetry_duplicates
    assert distinct == expected["valid_distinct_events"]


def test_every_record_validates_schema_and_model(sandbox_run: SandboxRun) -> None:
    records = recommendations(sandbox_run.results)
    assert records
    for rec in records:
        doc = rec.model_dump(mode="json", exclude_unset=True)
        assert contract_problems(doc) == []
        assert Recommendation.model_validate(doc) == rec
        assert CANONICAL_ID.match(rec.recommendation_id.root)
        assert rec.advisory is True
        assert rec.method == "rule"
        assert rec.generator is not None
        assert rec.schema_version.root == "1.0.0"
        assert rec.created_at.root == "2026-10-19T12:00:00Z"
        assert len(rec.evidence_ids) <= 200
    ids = [r.recommendation_id.root for r in records]
    assert len(ids) == len(set(ids))


def test_detections_cite_rule_carry_score_bounds_and_owner(sandbox_run: SandboxRun) -> None:
    detected = [r for r in sandbox_run.results if r.outcome == "detected"]
    assert detected
    for result in detected:
        rec = result.recommendation
        assert rec is not None
        assert rec.generator is not None
        assert rec.generator.generator_id.root == result.rule_id == rec.kind
        assert rec.generator.generator_version.root == result.rule_version
        assert rec.evidence_status == "sufficient"
        assert rec.score is not None and 0.0 <= rec.score <= 1.0
        assert rec.uncertainty.method == "rule_bound"
        assert rec.owner.resolution == "assigned"  # every sandbox agent has an owned_by relation
        assert rec.owner.owner_id is not None
        assert rec.coverage.method == "full"


def test_evaluation_is_deterministic(sandbox_run: SandboxRun) -> None:
    window = sandbox_run.source.observed_window()
    assert window is not None
    again = evaluate_rules(
        sandbox_run.source,
        scope=make_scope(tuple(sandbox_run.domains)),
        window_start=window[0],
        window_end=window[1],
        created_at=CREATED_AT,
    )
    first = [r.model_dump_json() for r in recommendations(sandbox_run.results)]
    assert [r.model_dump_json() for r in recommendations(again)] == first


def test_scope_limits_evaluation_to_allowed_domains(sandbox_run: SandboxRun) -> None:
    window = sandbox_run.source.observed_window()
    assert window is not None
    one: IdentityScope = make_scope((sandbox_run.domains[0],))
    results = evaluate_rules(
        sandbox_run.source,
        scope=one,
        window_start=window[0],
        window_end=window[1],
        created_at=CREATED_AT,
    )
    assert results
    for rec in recommendations(results):
        assert rec.domain_id.root == sandbox_run.domains[0]
    foreign = make_scope((sandbox_run.domains[0],), customer="othercorp")
    assert (
        evaluate_rules(
            sandbox_run.source,
            scope=foreign,
            window_start=window[0],
            window_end=window[1],
            created_at=CREATED_AT,
        )
        == []
    )
