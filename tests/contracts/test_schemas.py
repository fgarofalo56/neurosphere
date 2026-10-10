"""JSON Schema validation of every contract schema and golden example (PRP-01 item 7).

* every ``*.schema.json`` is valid against the draft 2020-12 metaschema;
* every non-library schema has at least one valid and one invalid example, and every
  example file on disk is claimed by exactly one manifest entry;
* valid examples validate; invalid examples fail, and where the area manifest names the
  expected failure (keyword, JSON Pointer, message fragment) that error is present;
* the audit examples form one hash chain (``validate_audit_chain``).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from contract_support import (
    DRAFT_2020_12,
    LIBRARY_SCHEMAS,
    ExampleCase,
    example_cases,
    example_files_on_disk,
    invalid_cases,
    iter_error_tree,
    json_pointer,
    load_json,
    load_schema,
    manifests,
    schema_errors,
    schema_files,
    valid_cases,
)
from jsonschema import Draft202012Validator
from validators import audit_record_hash, validate_audit_chain

_MISSING = object()


def _ids(cases: list[ExampleCase]) -> list[str]:
    return [c.case_id for c in cases]


@pytest.mark.parametrize("rel", schema_files())
def test_schema_is_valid_draft_2020_12(rel: str) -> None:
    schema = load_schema(rel)
    assert schema.get("$schema") == DRAFT_2020_12
    Draft202012Validator.check_schema(schema)


def test_library_allowlist_matches_manifest_declarations() -> None:
    declared = set()
    for area, (_, data) in manifests().items():
        for name in (data or {}).get("library_schemas", []):
            declared.add(f"{area}/{name}")
    assert declared == set(LIBRARY_SCHEMAS)
    for rel in LIBRARY_SCHEMAS:
        schema = load_schema(rel)
        assert "type" not in schema and "properties" not in schema, f"{rel} is not $defs-only"


def test_every_schema_has_valid_and_invalid_examples() -> None:
    counts: Counter[tuple[str, bool]] = Counter((c.schema, c.valid) for c in example_cases())
    missing = [
        f"{rel}: {'valid' if want else 'invalid'}"
        for rel in schema_files()
        if rel not in LIBRARY_SCHEMAS
        for want in (True, False)
        if counts[(rel, want)] == 0
    ]
    assert not missing, "schemas without golden examples:\n" + "\n".join(missing)
    stray = {c.schema for c in example_cases()} - set(schema_files())
    assert not stray, f"examples point at unknown schemas: {sorted(stray)}"
    assert not {c.schema for c in example_cases()} & LIBRARY_SCHEMAS


def test_every_example_file_is_claimed_exactly_once() -> None:
    claimed = Counter(c.file.resolve() for c in example_cases())
    duplicates = [str(p) for p, n in claimed.items() if n > 1]
    assert not duplicates, f"claimed more than once: {duplicates}"
    on_disk = example_files_on_disk()
    assert set(claimed) == on_disk, {
        "orphan files": sorted(str(p) for p in on_disk - set(claimed)),
        "missing files": sorted(str(p) for p in set(claimed) - on_disk),
    }


def test_examples_are_in_valid_or_invalid_buckets() -> None:
    wrong = [
        c.case_id
        for c in example_cases()
        if c.file.parent.name != ("valid" if c.valid else "invalid")
    ]
    assert not wrong, f"example stored in the wrong bucket: {wrong}"


@pytest.mark.parametrize("case", valid_cases(), ids=_ids(valid_cases()))
def test_valid_example_validates(case: ExampleCase) -> None:
    errors = schema_errors(case.schema, case.load())
    assert not errors, [f"{json_pointer(e.absolute_path)}: {e.message}" for e in errors]


@pytest.mark.parametrize("case", invalid_cases(), ids=_ids(invalid_cases()))
def test_invalid_example_fails_for_the_stated_reason(case: ExampleCase) -> None:
    errors = schema_errors(case.schema, case.load())
    assert errors, f"{case.case_id} unexpectedly validates against {case.schema}"
    if case.keyword is None:
        return
    assert case.instance_path is not None
    matches = [
        e
        for e in iter_error_tree(errors)
        if e.validator == case.keyword and json_pointer(e.absolute_path) == case.instance_path
    ]
    found = [(json_pointer(e.absolute_path), e.validator) for e in iter_error_tree(errors)]
    assert matches, f"expected {case.keyword!r} at {case.instance_path!r}; got {found}"
    if case.message_contains:
        assert any(case.message_contains in e.message for e in matches), [
            e.message for e in matches
        ]
    if case.area == "catalog/v1":
        # The catalog index promises "the single expected validation error".
        assert len(errors) == 1, [f"{json_pointer(e.absolute_path)} {e.validator}" for e in errors]


def _diff_paths(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            out += _diff_paths(a.get(key, _MISSING), b.get(key, _MISSING), f"{path}/{key}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out += _diff_paths(x, y, f"{path}/{i}")
        return out
    return [] if a == b and type(a) is type(b) else [path]


_DERIVED = [c for c in invalid_cases() if c.derived_from is not None]


@pytest.mark.parametrize("case", _DERIVED, ids=_ids(_DERIVED))
def test_derived_invalid_example_is_a_single_mutation(case: ExampleCase) -> None:
    """Manifests say each invalid example is a valid one with exactly one mutation: the
    changed members all sit under one parent (one value or one object replaced)."""
    assert case.derived_from is not None
    source = [c for c in valid_cases() if c.file.resolve() == case.derived_from.resolve()]
    assert source, f"derived_from {case.derived_from} is not a listed valid example"
    assert source[0].schema == case.schema
    changed = _diff_paths(load_json(case.derived_from), case.load())
    assert changed, "invalid example is identical to its source"
    parents = {p.rsplit("/", 1)[0] for p in changed}
    assert len(changed) == 1 or len(parents) == 1, changed


def test_audit_examples_form_one_hash_chain() -> None:
    """validate_audit_chain (named by audit-record.schema.json) over the valid examples."""
    records = [c.load() for c in valid_cases() if c.schema == "audit/v1/audit-record.schema.json"]
    assert len(records) >= 2
    assert validate_audit_chain(records) == []


def test_validate_audit_chain_detects_tampering() -> None:
    records = [c.load() for c in valid_cases() if c.schema == "audit/v1/audit-record.schema.json"]
    records.sort(key=lambda r: r["sequence"])
    head, second = dict(records[0]), dict(records[1])

    edited = {**second, "operation": "action.tampered"}
    assert any("record_hash mismatch" in p for p in validate_audit_chain([head, edited]))

    relinked = {**second, "previous_hash": "sha256:" + "0" * 64}
    relinked["record_hash"] = audit_record_hash(relinked)
    assert any("previous_hash" in p for p in validate_audit_chain([head, relinked]))

    assert any("not contiguous" in p for p in validate_audit_chain([second]))
    assert validate_audit_chain([second], require_head=False) == []
    gap = {**records[2], "sequence": 5}
    gap["record_hash"] = audit_record_hash(gap)
    assert any("not contiguous" in p for p in validate_audit_chain([head, second, gap]))
