"""Precision and recall on the sandbox duplicate set (pilot-set target, not a general claim).

Ground truth is the ``duplicate_agent_candidates`` pairs in ``anomaly-manifest.json``. The
baseline runs WITHOUT embeddings.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from types import ModuleType

from jsonschema import Draft202012Validator
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation

from neurosphere_workers.recommendations.duplicates import DuplicateConfig, DuplicateRun

from .support import CREATED_AT, PROFILE_NAME, REPO_ROOT, SEED, Estate, pair_of

SCHEMA = REPO_ROOT / "packages" / "contracts" / "schemas" / "recommendations" / "v1"
CONTRACT_TESTS = REPO_ROOT / "tests" / "contracts"
PRECISION_TARGET = 0.80


def _contract_validators() -> ModuleType:
    """Load tests/contracts/validators.py (it imports its sibling ``contract_support``)."""
    sys.path.insert(0, str(CONTRACT_TESTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "dup_contract_validators", CONTRACT_TESTS / "validators.py"
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CONTRACT_TESTS))


def test_precision_at_least_80_percent_and_recall_reported(
    estate: Estate, default_run: DuplicateRun
) -> None:
    truth = estate.duplicate_pairs
    predicted = {pair_of(c.recommendation) for c in default_run.candidates}
    true_positive = predicted & truth
    precision = len(true_positive) / len(predicted) if predicted else 0.0
    recall = len(true_positive) / len(truth)
    print(
        f"\nduplicates: sandbox profile={PROFILE_NAME} seed={SEED} "
        f"ground-truth pairs={len(truth)} predicted={len(predicted)} "
        f"true-positive={len(true_positive)} precision={precision:.3f} recall={recall:.3f} "
        f"review-candidates={len(default_run.review_candidates)} "
        f"pairs-compared={default_run.pairs_compared} truncated={default_run.truncated}"
    )
    assert len(truth) >= 5
    assert predicted, "no candidate emitted at all"
    assert precision >= PRECISION_TARGET
    assert not default_run.truncated


def test_review_candidates_are_not_recommendations(default_run: DuplicateRun) -> None:
    cfg = DuplicateConfig()
    recommended = {pair_of(c.recommendation) for c in default_run.candidates}
    assert default_run.review_candidates, "the sandbox has near-duplicates below the threshold"
    for review in default_run.review_candidates:
        assert cfg.review_floor <= review.similarity < cfg.min_similarity
        assert frozenset(review.subject_ids) not in recommended
    for candidate in default_run.candidates:
        assert candidate.recommendation.score is not None
        assert candidate.recommendation.score >= cfg.min_similarity


def test_every_record_validates_against_schema_model_and_cross_field_rules(
    default_run: DuplicateRun,
) -> None:
    validators = _contract_validators()
    schema = json.loads((SCHEMA / "recommendation.schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema)
    assert default_run.candidates
    for candidate in default_run.candidates:
        rec = candidate.recommendation
        # exclude_unset keeps the explicit nulls the schema requires (owner_id, observed_fraction).
        doc = rec.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert list(schema_validator.iter_errors(doc)) == []
        assert Recommendation.model_validate(doc) == rec
        assert validators.check_recommendation_score_interval(doc) == []
        assert validators.check_recommendation_same_boundary(doc) == []
        assert validators.check_time_range_order(doc["evidence_window"]) == []
        assert rec.kind == "candidate_duplicate"
        assert rec.advisory is True
        assert rec.method == "statistical"
        assert rec.evidence_status == "sufficient"
        subjects = [s.root for s in rec.subject_ids]
        assert subjects == sorted(subjects)
        assert len(subjects) == 2
        assert rec.uncertainty.method == "rule_bound"
        assert rec.uncertainty.lower is not None
        assert rec.uncertainty.upper is not None
        assert rec.score is not None
        assert rec.uncertainty.lower <= rec.score <= rec.uncertainty.upper
        assert rec.created_at.root == CREATED_AT
        kinds = {p.kind: p.status for p in rec.prerequisites}
        assert kinds["approval"] in {"unmet", "unknown"}
        assert kinds["owner_consent"] in {"unmet", "unknown"}
        assert rec.generator is not None
        assert rec.generator.generator_id.root == default_run.generator_id
        assert rec.generator.generator_version.root == default_run.generator_version
        assert rec.schema_version.root == "1.0.0"
        # The id must itself satisfy the canonical-ID grammar (no underscore in the last segment).
        rec_id = rec.recommendation_id.root
        assert re.fullmatch(
            r"commercial:synthco:neurosphere:recommendation:candidate-duplicate-[0-9a-f]{24}",
            rec_id,
        )
        assert validators.CANONICAL_ID_RE.fullmatch(rec_id)
        # Evidence cites the supporting relation ids; the breakdown names the shared targets.
        assert rec.evidence_ids
        b = candidate.breakdown
        assert b.shared_source_ids or b.shared_model_deployment_ids or b.shared_tool_ids
        assert b.same_domain_id == rec.domain_id.root


def test_recommendation_id_hash_convention(default_run: DuplicateRun, estate: Estate) -> None:
    first = default_run.candidates[0].recommendation
    basis = "|".join(
        [
            default_run.generator_id,
            default_run.generator_version,
            *sorted(s.root for s in first.subject_ids),
            estate.window.start.root,
            estate.window.end.root,
        ]
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    assert first.recommendation_id.root.endswith(f"candidate-duplicate-{digest}")


def test_ids_unique_and_output_sorted_by_similarity(default_run: DuplicateRun) -> None:
    ids = [c.recommendation.recommendation_id.root for c in default_run.candidates]
    assert len(set(ids)) == len(ids)
    scores = [c.recommendation.score or 0.0 for c in default_run.candidates]
    assert scores == sorted(scores, reverse=True)


def test_owner_comes_from_owned_by(default_run: DuplicateRun) -> None:
    resolved = [
        c.recommendation.owner for c in default_run.candidates if c.recommendation.owner.owner_id
    ]
    assert resolved, "sandbox duplicates share an owner"
    for owner in resolved:
        assert owner.resolution == "assigned"
        assert owner.owner_id is not None
        assert ":owner:" in owner.owner_id.root
