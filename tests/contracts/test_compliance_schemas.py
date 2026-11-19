"""compliance/v1 contracts (PRP-56 item 1).

The generic example suites (test_schemas.py) already validate every example; this module pins
what is specific to the family: the summary vocabulary has no verdict word, unknown numbers are
``null`` and never 0, and the generated models agree with the JSON Schema.
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from typing import Any

import pytest
from contract_support import REPO_ROOT, SCHEMA_ROOT, load_json, model_for, schema_errors
from pydantic import ValidationError

BUNDLE = "compliance/v1/evidence-bundle.schema.json"
OBSERVATION = "compliance/v1/evidence-observation.schema.json"
MAPPING = "compliance/v1/control-mapping.schema.json"
EXAMPLES = SCHEMA_ROOT / "compliance" / "v1" / "examples" / "valid"

VERDICT_WORDS = ("pass", "fail", "compliant", "score", "percent", "certified", "authorized")


def _bundle() -> dict[str, Any]:
    return load_json(EXAMPLES / "evidence-bundle.single-control.json")


def test_summary_outside_the_four_words_is_rejected() -> None:
    doc = _bundle()
    doc["controls"][0]["summary"] = "compliant"
    assert schema_errors(BUNDLE, doc)
    with pytest.raises(ValidationError):
        model_for(BUNDLE).model_validate(doc)


@pytest.mark.parametrize(
    "summary", ["evidence_present", "evidence_partial", "no_evidence", "customer_responsibility"]
)
def test_each_summary_word_validates(summary: str) -> None:
    doc = _bundle()
    doc["controls"][0]["summary"] = summary
    assert schema_errors(BUNDLE, doc) == []
    model_for(BUNDLE).model_validate(doc)


def test_observation_status_vocabulary_is_exactly_four() -> None:
    schema = load_json(SCHEMA_ROOT / OBSERVATION)
    assert schema["properties"]["status"]["enum"] == [
        "observed",
        "partial",
        "unavailable",
        "not_collected",
    ]


def test_support_status_is_the_prp23_six() -> None:
    schema = load_json(SCHEMA_ROOT / MAPPING)
    assert schema["$defs"]["support_status"]["enum"] == [
        "designed",
        "implemented_tested",
        "inherited",
        "customer",
        "planned",
        "not_applicable",
    ]


def test_no_verdict_word_in_any_enum() -> None:
    for path in sorted((SCHEMA_ROOT / "compliance" / "v1").glob("*.schema.json")):
        text = path.read_text(encoding="utf-8")
        schema = load_json(path)
        enums: list[str] = []

        def walk(node: Any, enums: list[str] = enums) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "enum":
                        enums.extend(str(v) for v in value)
                    else:
                        walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schema)
        assert text
        for word in VERDICT_WORDS:
            assert not [e for e in enums if word in e.split("_")], (path.name, word)


def test_unknown_count_is_null_and_zero_is_a_real_zero() -> None:
    doc = load_json(EXAMPLES / "evidence-observation.observed.json")
    doc["measures"] = [{"name": "owners", "value": None}, {"name": "overdue", "value": 0}]
    assert schema_errors(OBSERVATION, doc) == []
    model = model_for(OBSERVATION).model_validate(doc)
    values = [m.value for m in model.measures]
    assert values == [None, 0]


def test_a_count_cannot_be_negative_or_a_string() -> None:
    for bad in (-1, "unknown"):
        doc = copy.deepcopy(load_json(EXAMPLES / "evidence-observation.observed.json"))
        doc["measures"] = [{"name": "owners", "value": bad}]
        assert schema_errors(OBSERVATION, doc)


def test_bundle_carries_no_member_that_could_hold_a_verdict_or_body() -> None:
    schema = load_json(SCHEMA_ROOT / BUNDLE)
    assert set(schema["properties"]) == {
        "schema_version",
        "framework_id",
        "framework_version",
        "library_version",
        "domain_id",
        "generated_at",
        "window_start",
        "window_end",
        "controls",
        "observations",
        "digest",
    }
    assert schema["additionalProperties"] is False


CONTROL = "compliance/v1/control.schema.json"
FRAMEWORK_IDS = (
    "nist_ai_rmf",
    "sr_11_7",
    "hipaa_technical_safeguards",
    "omb_m_25_21",
    "soc2_tsc",
    "iso_27001_annex_a",
    "gdpr",
    "nist_800_53_r5",
    "eu_ai_act",
    "iso_42001",
)
CLAIM_WORDS = re.compile(
    r"complian|certif|\bmeets?\b|\bsatisf|authori[sz]ed|\bATO\b|FedRAMP", re.IGNORECASE
)


def _claims_rules() -> Any:
    path = REPO_ROOT / "tests" / "marketing" / "claims_rules.py"
    spec = importlib.util.spec_from_file_location("claims_rules_for_contracts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need this before exec
    spec.loader.exec_module(module)
    return module


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_all_ten_framework_ids_validate_on_a_control() -> None:
    base = load_json(EXAMPLES / "control.nist-govern-2.json")
    schema = load_json(SCHEMA_ROOT / CONTROL)
    assert tuple(schema["$defs"]["framework_id"]["enum"]) == FRAMEWORK_IDS
    for framework_id in FRAMEWORK_IDS:
        doc = {**base, "framework_id": framework_id}
        assert schema_errors(CONTROL, doc) == [], framework_id
        model_for(CONTROL).model_validate(doc)


def test_an_unknown_framework_id_is_rejected() -> None:
    doc = {**load_json(EXAMPLES / "control.nist-govern-2.json"), "framework_id": "pci_dss_4"}
    assert schema_errors(CONTROL, doc)
    with pytest.raises(ValidationError):
        model_for(CONTROL).model_validate(doc)


def test_framework_id_description_says_open_ended() -> None:
    schema = load_json(SCHEMA_ROOT / CONTROL)
    assert "tolerate unknown values" in schema["$defs"]["framework_id"]["description"]


def test_every_framework_id_has_a_valid_control_example() -> None:
    seen = {load_json(p)["framework_id"] for p in sorted(EXAMPLES.glob("control.*.json"))}
    assert seen >= set(FRAMEWORK_IDS[4:]) | {"nist_ai_rmf"}


def test_every_valid_compliance_example_passes_the_no_claims_wording_check() -> None:
    # Valid examples only: the invalid ones carry verdict words on purpose, to prove rejection.
    rules = _claims_rules()
    paths = sorted(EXAMPLES.glob("*.json"))
    assert paths
    for path in paths:
        for text in _strings(load_json(path)):
            assert not rules.find_violations(text), (path.name, text)
            if path.name.startswith(
                "control."
            ):  # other files hold repo paths such as .../compliance/...
                assert not CLAIM_WORDS.search(text), (path.name, text)
