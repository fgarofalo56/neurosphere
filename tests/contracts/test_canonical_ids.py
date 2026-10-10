"""Canonical ID grammar ``cloud:customer:source:type:id`` (Clarification 7) against the
catalog corpus, through three engines: Python ``re.fullmatch``, the ``jsonschema``
validator and the generated Pydantic model.

Python ``re`` lets ``$`` match before a trailing newline, and the ``jsonschema`` library
evaluates ``pattern`` with ``re.search``; so the corpus entry ``"...:abc\\n"`` passes
JSON Schema validation in Python while ECMA-262 engines (and Pydantic's Rust regex) reject
it. That gap is asserted explicitly, and ``validate_canonical_id_fullmatch`` closes it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors
from pydantic import ValidationError
from validators import (
    CANONICAL_ID_PATTERN,
    canonical_id_fullmatches,
    validate_canonical_id_fullmatch,
    validate_target_ref_matches_catalog_grammar,
)

SCHEMA = "catalog/v1/canonical_id.schema.json"
CORPUS = load_json(SCHEMA_ROOT / "catalog/v1/id-corpus.json")
VALID: list[str] = CORPUS["valid"]
INVALID: list[dict[str, str]] = CORPUS["invalid"]
TRAILING_NEWLINE = [e["value"] for e in INVALID if e["value"].endswith("\n")]


def _pydantic_accepts(value: str) -> bool:
    try:
        model_for(SCHEMA).model_validate(value)
    except ValidationError:
        return False
    return True


def test_corpus_size_and_coverage() -> None:
    assert len(VALID) >= 30
    assert len(INVALID) >= 30
    reasons = " ".join(e["reason"] for e in INVALID).lower()
    for topic in ("colon", "uppercase", "trailing newline", "empty"):
        assert topic in reasons, topic
    assert CORPUS["schema"] == "canonical_id.schema.json"


def test_validator_pattern_is_the_schema_pattern() -> None:
    assert load_schema(SCHEMA)["pattern"] == CANONICAL_ID_PATTERN


@pytest.mark.parametrize("value", VALID)
def test_valid_ids_pass_every_engine(value: str) -> None:
    assert re.fullmatch(load_schema(SCHEMA)["pattern"], value)
    assert canonical_id_fullmatches(value)
    assert schema_errors(SCHEMA, value) == []
    assert _pydantic_accepts(value)
    assert validate_canonical_id_fullmatch(value) == []
    assert len(value.split(":")) == 5


@pytest.mark.parametrize("entry", INVALID, ids=[e["reason"] for e in INVALID])
def test_invalid_ids_fail_fullmatch_and_pydantic(entry: dict[str, str]) -> None:
    value = entry["value"]
    assert re.fullmatch(load_schema(SCHEMA)["pattern"], value) is None
    assert validate_canonical_id_fullmatch(value)
    assert not _pydantic_accepts(value)


@pytest.mark.parametrize(
    "entry", [e for e in INVALID if e["value"] not in TRAILING_NEWLINE], ids=lambda e: e["reason"]
)
def test_invalid_ids_fail_json_schema(entry: dict[str, str]) -> None:
    assert schema_errors(SCHEMA, entry["value"])


def test_trailing_newline_gap_is_real_and_closed() -> None:
    """Documents the engine difference (ADR-0004) so nobody relies on jsonschema alone."""
    assert TRAILING_NEWLINE, "corpus must keep a trailing-newline case"
    pattern = load_schema(SCHEMA)["pattern"]
    for value in TRAILING_NEWLINE:
        assert re.match(pattern, value) is not None  # the '$' trap
        assert re.search(pattern, value) is not None
        assert re.fullmatch(pattern, value) is None
        assert schema_errors(SCHEMA, value) == [], "jsonschema uses re.search; '$' matches"
        assert validate_canonical_id_fullmatch(value)
        assert not _pydantic_accepts(value)


def test_validate_target_ref_matches_catalog_grammar(id_corpus: dict[str, Any]) -> None:
    target_ref = load_schema("actions/v1/target-ref.schema.json")
    assert (
        validate_target_ref_matches_catalog_grammar(target_ref, load_schema(SCHEMA), id_corpus)
        == []
    )
    drifted = {
        **target_ref,
        "properties": {
            **target_ref["properties"],
            "canonical_id": {**target_ref["properties"]["canonical_id"], "pattern": "^[a-z:]+$"},
        },
    }
    assert validate_target_ref_matches_catalog_grammar(drifted, load_schema(SCHEMA), id_corpus)


MIRRORS = [
    ("telemetry/v1/telemetry-event.schema.json", "/$defs/canonical_id/pattern"),
    ("scope/v1/identity-scope.schema.json", "/$defs/canonical_id/pattern"),
    ("query/v1/structured-query.schema.json", "/$defs/canonical_id/pattern"),
    ("recommendations/v1/recommendation.schema.json", "/$defs/canonical_id/pattern"),
    ("evaluation/v1/evaluation-result.schema.json", "/$defs/canonical_id/pattern"),
    ("actions/v1/target-ref.schema.json", "/properties/canonical_id/pattern"),
    ("catalog/v1/alias.schema.json", "/properties/canonical_id/pattern"),
]


@pytest.mark.parametrize(("rel", "pointer"), MIRRORS, ids=[m[0] for m in MIRRORS])
def test_mirrored_patterns_equal_the_catalog_grammar(rel: str, pointer: str) -> None:
    node: Any = load_schema(rel)
    for part in pointer.strip("/").split("/"):
        node = node[part]
    assert node == CANONICAL_ID_PATTERN, f"{rel}{pointer} drifted from the catalog grammar"
