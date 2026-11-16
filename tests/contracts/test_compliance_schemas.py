"""compliance/v1 contracts (PRP-56 item 1).

The generic example suites (test_schemas.py) already validate every example; this module pins
what is specific to the family: the summary vocabulary has no verdict word, unknown numbers are
``null`` and never 0, and the generated models agree with the JSON Schema.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, model_for, schema_errors
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
