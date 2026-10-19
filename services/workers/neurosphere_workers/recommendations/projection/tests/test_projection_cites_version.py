"""Projections cite the price version, validate against the contract and fail closed.

Fixture snapshots only; no network.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger.models import TokenCounts
from neurosphere_core.pricing import (
    FIXTURE_DIR,
    InMemoryPriceSnapshotStore,
    PriceRow,
    TokenMeter,
    build_snapshot,
    load_snapshot_file,
)
from neurosphere_workers.recommendations.projection import (
    CandidatePair,
    CandidatePairConfig,
    UsageSummary,
    compare_model_costs,
    project_right_sizing,
    project_right_sizing_candidates,
    recommendation_id,
)

REPO = Path(__file__).resolve().parents[6]
SCHEMA = REPO / "packages/contracts/schemas/recommendations/v1/recommendation.schema.json"
sys.path.insert(0, str(REPO / "tests" / "contracts"))
validators = importlib.import_module("validators")  # tests/contracts helpers

CREATED = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
AGENT = "commercial:acme:foundry:agent:support-bot"
DOMAIN = "commercial:acme:catalog:domain:support"
OWNER = "commercial:acme:entra:user:owner-1"

PAIR = CandidatePair(
    pair_id="large-to-mini",
    provider="azure_openai",
    current_model="gpt-4.1",
    candidate_model="gpt-4.1-mini",
    candidate_model_version="2025-04-14",
)
CONFIG = CandidatePairConfig(config_id="pairs", version="2026.10.1", pairs=(PAIR,))


def commercial_store() -> InMemoryPriceSnapshotStore:
    return InMemoryPriceSnapshotStore(
        [load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json")]
    )


def usage(**over: Any) -> UsageSummary:
    fields: dict[str, Any] = {
        "agent_id": AGENT,
        "cloud": "commercial",
        "customer_id": "acme",
        "domain_id": DOMAIN,
        "owner_id": OWNER,
        "provider": "azure_openai",
        "current_model": "gpt-4.1",
        "current_model_version": "2025-04-14",
        "tokens": TokenCounts(input=2_000_000, output=500_000, cached=500_000),
        "window_start": datetime(2026, 10, 1, tzinfo=UTC),
        "window_end": datetime(2026, 10, 15, tzinfo=UTC),
        "evidence_ids": ("ledger:2026-10:support-bot",),
        "coverage_method": "sampled",
        "observed_fraction": 0.5,
    }
    fields.update(over)
    return UsageSummary(**fields)


def assert_valid(record: Recommendation) -> dict[str, Any]:
    doc = record.model_dump(mode="json", exclude_unset=True)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(doc)
    assert validators.check_time_range_order(doc) == []
    assert validators.check_recommendation_score_interval(doc) == []
    assert validators.check_recommendation_same_boundary(doc) == []
    return doc


def test_projection_cites_price_version_and_effective_date() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None
    doc = assert_valid(record)
    est = doc["projected_estimate"]
    assert est["price_version"] == "synthetic-retail-2026-10"
    assert est["price_effective_date"] == "2026-10-01"
    assert est["estimate_kind"] == "estimated"
    assert est["period"] == "evidence_window"
    assert est["currency"] == "USD"
    assert doc["kind"] == "model_right_sizing"
    assert doc["advisory"] is True


def test_amounts_are_exact_decimal_strings() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None and record.projected_estimate is not None
    est = record.projected_estimate
    # gpt-4.1: 1.5M*2.0 + 0.5M*8.0 + 0.5M cached*0.5 = 7.25 ; mini: 0.6 + 0.8 + 0.05 = 1.45
    assert est.baseline_amount.root == "7.250000000000"
    assert est.projected_amount.root == "1.450000000000"
    assert all(isinstance(a.root, str) for a in (est.baseline_amount, est.projected_amount))


def test_uncertainty_range_follows_documented_method() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None and record.projected_estimate is not None
    est = record.projected_estimate
    # band 0.20, observed fraction 0.5: lower x0.8, upper x(1.2 / 0.5) = x2.4
    assert est.lower_amount is not None and est.upper_amount is not None
    assert Decimal(est.lower_amount.root) == Decimal("1.16")
    assert Decimal(est.upper_amount.root) == Decimal("3.48")
    assert record.uncertainty.method == "rule_bound"
    assert record.uncertainty.lower == pytest.approx(0.8)
    assert record.uncertainty.upper == pytest.approx(2.4)


def test_unknown_coverage_is_not_estimable_without_bounds() -> None:
    record = project_right_sizing(
        usage(observed_fraction=None, coverage_method="unknown"),
        PAIR,
        CONFIG,
        commercial_store(),
        created_at=CREATED,
    )
    assert record is not None and record.projected_estimate is not None
    assert record.uncertainty.method == "not_estimable"
    assert record.projected_estimate.lower_amount is None
    assert record.projected_estimate.upper_amount is None
    assert record.coverage.observed_fraction is None
    assert_valid(record)


def test_no_score_and_insufficient_evidence_no_fabricated_confidence() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None
    assert record.score is None
    assert record.evidence_status == "insufficient_evidence"
    assert record.method == "rule"


def test_prerequisites_are_open_and_cost_comparison_cites_snapshot() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None
    status = {p.kind: p.status for p in record.prerequisites}
    for kind in (
        "capability_compatibility",
        "context_compatibility",
        "tool_compatibility",
        "quality_regression_test",
        "staged_rollout_plan",
        "rollback_plan",
    ):
        assert status[kind] in {"unknown", "unmet"}
    assert status["cost_comparison"] == "met"
    cost = next(p for p in record.prerequisites if p.kind == "cost_comparison")
    assert cost.evidence_ids is not None
    assert [e.root for e in cost.evidence_ids] == ["synthetic-retail-2026-10"]


def test_record_id_follows_shared_convention() -> None:
    record = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert record is not None
    generator_id = "projection.right-sizing.pairs.large-to-mini"
    material = "|".join(
        [generator_id, "2026.10.1", AGENT, "2026-10-01T00:00:00Z", "2026-10-15T00:00:00Z"]
    )
    h = hashlib.sha256(material.encode()).hexdigest()[:24]
    assert record.recommendation_id.root == (
        f"commercial:acme:neurosphere:recommendation:model-right-sizing-{h}"
    )
    assert record.created_at.root == "2026-10-20T08:00:00Z"
    again = project_right_sizing(usage(), PAIR, CONFIG, commercial_store(), created_at=CREATED)
    assert again is not None and again.recommendation_id == record.recommendation_id


def test_recommendation_id_sorts_subjects() -> None:
    kwargs: dict[str, Any] = {
        "cloud": "commercial",
        "customer_id": "acme",
        "kind": "model_right_sizing",
        "generator_id": "g",
        "generator_version": "1",
        "window_start": "a",
        "window_end": "b",
    }
    assert recommendation_id(subject_ids=["x", "y"], **kwargs) == recommendation_id(
        subject_ids=["y", "x"], **kwargs
    )


def test_unresolvable_price_version_is_rejected_with_invalid_schema() -> None:
    empty = InMemoryPriceSnapshotStore()
    with pytest.raises(InvalidSchemaError) as caught:
        project_right_sizing(usage(), PAIR, CONFIG, empty, created_at=CREATED)
    assert caught.value.code == "invalid_schema"
    assert caught.value.reason == "price_unresolved"


def test_window_before_any_effective_date_is_unresolved() -> None:
    early = usage(
        window_start=datetime(2026, 9, 1, tzinfo=UTC), window_end=datetime(2026, 9, 10, tzinfo=UTC)
    )
    with pytest.raises(InvalidSchemaError):
        project_right_sizing(early, PAIR, CONFIG, commercial_store(), created_at=CREATED)


def test_window_ending_at_midnight_prices_the_previous_day() -> None:
    # Half-open window ending exactly at 2026-10-01T00:00Z last touches 2026-09-30.
    boundary = usage(
        window_start=datetime(2026, 9, 20, tzinfo=UTC), window_end=datetime(2026, 10, 1, tzinfo=UTC)
    )
    with pytest.raises(InvalidSchemaError):
        project_right_sizing(boundary, PAIR, CONFIG, commercial_store(), created_at=CREATED)


def test_candidate_missing_from_snapshot_is_unresolved() -> None:
    pair = PAIR.model_copy(update={"candidate_model": "not-a-model"})
    with pytest.raises(InvalidSchemaError) as caught:
        project_right_sizing(usage(), pair, CONFIG, commercial_store(), created_at=CREATED)
    assert caught.value.reason == "price_unresolved"


def test_candidate_never_priced_from_a_different_snapshot() -> None:
    older = build_snapshot(
        snapshot_id="older-sheet",
        source="provider_price_sheet",
        source_url="https://pricing.invalid/older",
        retrieval_date=date(2026, 9, 1),
        effective_date=date(2026, 9, 1),
        currency="USD",
        clouds=("commercial",),
        rows=[
            PriceRow(
                service_name="s",
                sku_name=f"o-{kind}",
                unit_of_measure="1M",
                retail_price=Decimal(1),
                token_meter=TokenMeter(provider="azure_openai", model="only-old", kind=kind),
            )
            for kind in ("input", "output")
        ],
    )
    store = commercial_store()
    store.put(older)
    pair = PAIR.model_copy(update={"candidate_model": "only-old"})
    with pytest.raises(InvalidSchemaError):
        compare_model_costs(usage(), pair, store)


@pytest.mark.parametrize(
    "tokens",
    [
        TokenCounts(input=None, output=100),
        TokenCounts(input=100, output=None),
        TokenCounts(),
    ],
)
def test_unknown_tokens_yield_no_projection(tokens: TokenCounts) -> None:
    got = project_right_sizing(
        usage(tokens=tokens), PAIR, CONFIG, commercial_store(), created_at=CREATED
    )
    assert got is None


def test_cached_tokens_without_candidate_cached_rate_yield_no_projection() -> None:
    pair = PAIR.model_copy(
        update={"candidate_model": "gpt-4.1-nano", "candidate_model_version": "2025-04-14"}
    )
    got = project_right_sizing(usage(), pair, CONFIG, commercial_store(), created_at=CREATED)
    assert got is None  # nano has no cached rate in the fixture; never guess it


def test_zero_tokens_are_a_real_zero_not_unknown() -> None:
    record = project_right_sizing(
        usage(tokens=TokenCounts(input=0, output=0)),
        PAIR,
        CONFIG,
        commercial_store(),
        created_at=CREATED,
    )
    assert record is not None and record.projected_estimate is not None
    assert record.projected_estimate.baseline_amount.root == "0.000000000000"


def test_naive_created_at_is_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        project_right_sizing(
            usage(),
            PAIR,
            CONFIG,
            commercial_store(),
            created_at=datetime(2026, 10, 20, 8, 0),
        )


def test_unresolved_owner_is_reported_as_unresolved() -> None:
    record = project_right_sizing(
        usage(owner_id=None), PAIR, CONFIG, commercial_store(), created_at=CREATED
    )
    assert record is not None
    assert record.owner.resolution == "unresolved" and record.owner.owner_id is None
    assert_valid(record)


def test_deployment_is_an_additional_subject() -> None:
    deployment = "commercial:acme:foundry:deployment:gpt-4-1-prod"
    record = project_right_sizing(
        usage(deployment_id=deployment), PAIR, CONFIG, commercial_store(), created_at=CREATED
    )
    assert record is not None
    assert [s.root for s in record.subject_ids] == [AGENT, deployment]
    assert_valid(record)


def test_usage_outside_customer_boundary_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        usage(agent_id="commercial:other:foundry:agent:x")


def test_batch_emits_matches_and_records_skips() -> None:
    other = usage(
        agent_id="commercial:acme:foundry:agent:unknown-tokens",
        tokens=TokenCounts(input=None, output=None),
    )
    no_pair = usage(
        agent_id="commercial:acme:foundry:agent:other-model", current_model="gpt-4.1-nano"
    )
    batch = project_right_sizing_candidates(
        [usage(), other, no_pair], CONFIG, commercial_store(), created_at=CREATED
    )
    assert len(batch.recommendations) == 1
    assert [(s.agent_id, s.reason) for s in batch.skipped] == [
        ("commercial:acme:foundry:agent:unknown-tokens", "tokens_unknown")
    ]
    for record in batch.recommendations:
        assert_valid(record)


def test_batch_with_unresolved_price_emits_nothing() -> None:
    batch = project_right_sizing_candidates(
        [usage()], CONFIG, InMemoryPriceSnapshotStore(), created_at=CREATED
    )
    assert batch.recommendations == ()
    assert [s.reason for s in batch.skipped] == ["price_unresolved"]
