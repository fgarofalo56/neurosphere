"""PRP-61 item 1: the two deterministic finding kinds and their score rules."""

from __future__ import annotations

import copy

import pytest
from contract_support import SCHEMA_ROOT, load_json
from jsonschema import Draft202012Validator
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation

AREA = SCHEMA_ROOT / "recommendations" / "v1"
NEW_KINDS = ("configuration_finding", "unregistered_ai_resource")


def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_json(AREA / "recommendation.schema.json"))


def _finding(kind: str = "configuration_finding") -> dict:
    doc = load_json(AREA / "examples" / "valid" / "recommendation.configuration-finding.json")
    doc["kind"] = kind
    return doc


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_sufficient_without_score_is_valid_for_finding_kinds(kind: str) -> None:
    doc = _finding(kind)
    assert "score" not in doc
    assert list(_validator().iter_errors(doc)) == []
    Recommendation.model_validate(doc)


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_finding_kinds_must_be_advisory_rule(kind: str) -> None:
    v = _validator()
    bad = _finding(kind)
    bad["advisory"] = False
    assert list(v.iter_errors(bad))
    bad = _finding(kind)
    bad["method"] = "ml"
    assert list(v.iter_errors(bad))


def test_other_kinds_still_need_a_score_when_sufficient() -> None:
    doc = _finding("cost_spike")
    assert list(_validator().iter_errors(doc))
    scored = copy.deepcopy(doc)
    scored["score"] = 0.5
    scored["uncertainty"] = {"method": "rule_bound", "lower": 0.1, "upper": 0.9}
    assert list(_validator().iter_errors(scored)) == []


def test_insufficient_evidence_never_carries_a_score() -> None:
    doc = _finding()
    doc["evidence_status"] = "insufficient_evidence"
    doc["score"] = 0.5
    assert list(_validator().iter_errors(doc))
