"""Cross-schema structural walkers (PRP-01 conventions and gotchas).

* every ``$ref`` is a local fragment or a relative file ref that resolves to a schema in
  this tree (no remote URLs, so the suite runs with NO_NETWORK=1), and its fragment exists;
* ``$id`` follows ``https://neurosphere.invalid/schemas/<area>/v1/<name>.schema.json`` and
  matches the file location;
* every ``type: object`` node closes itself with ``additionalProperties: false``
  (Clarification 6), except sub-schemas under ``if``/``then``/``else``/``not``/``contains``,
  which only constrain members already declared by the enclosing closed object;
* property names, ``required`` entries and ``$defs`` names are snake_case, except inside
  the chart ``spec`` subtree, which keeps Vega-Lite camelCase (documented exception).
"""

from __future__ import annotations

import re

import pytest
from contract_support import (
    ID_PREFIX,
    SCHEMA_ROOT,
    SubSchema,
    iter_subschemas,
    load_schema,
    ref_target,
    refs_of,
    resolve_pointer,
    schema_files,
)

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
CHART = "chart/v1/chart-plan.schema.json"
# Chart $defs that are not part of the Vega-Lite spec subtree keep the snake_case rule.
CHART_NON_SPEC_DEFS = frozenset({"schema_version", "timestamp", "citation"})


@pytest.mark.parametrize("rel", schema_files())
def test_refs_are_relative_and_resolve_offline(rel: str) -> None:
    problems = []
    for pointer, ref in refs_of(rel):
        target, fragment = ref_target(rel, ref)
        if "://" in ref or ref.startswith(("//", "/")):
            problems.append(f"{pointer}: remote or absolute $ref {ref!r}")
            continue
        if target is None or not (SCHEMA_ROOT / target).is_file():
            problems.append(f"{pointer}: $ref {ref!r} does not resolve to a local schema")
            continue
        try:
            resolve_pointer(load_schema(target), fragment)
        except (KeyError, IndexError, ValueError):
            problems.append(f"{pointer}: fragment #{fragment} missing in {target}")
    assert not problems, problems


@pytest.mark.parametrize("rel", schema_files())
def test_id_pattern_matches_location(rel: str) -> None:
    schema_id = load_schema(rel)["$id"]
    assert re.fullmatch(
        r"https://neurosphere\.invalid/schemas/[a-z]+/v1/[a-z0-9_-]+\.schema\.json", schema_id
    )
    assert schema_id == ID_PREFIX + rel


@pytest.mark.parametrize("rel", schema_files())
def test_no_dynamic_or_remote_keywords(rel: str) -> None:
    for sub in iter_subschemas(load_schema(rel)):
        assert "$dynamicRef" not in sub.node and "$recursiveRef" not in sub.node, sub.pointer
        assert sub.node.get("format") not in ("uri", "uri-reference", "iri", "iri-reference"), (
            sub.pointer
        )


def _is_object_node(sub: SubSchema) -> bool:
    kind = sub.node.get("type")
    return kind == "object" or (isinstance(kind, list) and "object" in kind)


@pytest.mark.parametrize("rel", schema_files())
def test_every_object_forbids_additional_properties(rel: str) -> None:
    open_objects = [
        sub.pointer or "/"
        for sub in iter_subschemas(load_schema(rel))
        if _is_object_node(sub)
        and not sub.under_conditional
        and sub.node.get("additionalProperties") is not False
        and sub.node.get("unevaluatedProperties") is not False
    ]
    assert not open_objects, f"objects without additionalProperties: false: {open_objects}"


def test_conditional_exemption_is_narrow() -> None:
    """The exemption only covers conditional sub-schemas; count them so a schema cannot
    hide an open object by wrapping it in an if/then."""
    exempt = [
        (rel, sub.pointer)
        for rel in schema_files()
        for sub in iter_subschemas(load_schema(rel))
        if _is_object_node(sub)
        and sub.under_conditional
        and sub.node.get("additionalProperties") is not False
    ]
    for rel, pointer in exempt:
        node = resolve_pointer(load_schema(rel), pointer)
        assert set(node) <= {"type", "description"}, (
            f"{rel}{pointer} declares shape inside a conditional"
        )


def _in_chart_spec(rel: str, pointer: str) -> bool:
    if rel != CHART or not pointer.startswith("/$defs/"):
        return False
    return pointer.split("/")[2] not in CHART_NON_SPEC_DEFS


@pytest.mark.parametrize("rel", schema_files())
def test_keys_are_snake_case(rel: str) -> None:
    bad = []
    for sub in iter_subschemas(load_schema(rel)):
        if _in_chart_spec(rel, sub.pointer):
            continue
        names = list(sub.node.get("properties", {}))
        names += [r for r in sub.node.get("required", []) if isinstance(r, str)]
        if sub.pointer == "":
            names += list(sub.node.get("$defs", {}))
        bad += [f"{sub.pointer or '/'}: {n}" for n in names if not SNAKE.fullmatch(n)]
    assert not bad, bad


def test_chart_spec_exception_is_used() -> None:
    """The exception exists for real camelCase Vega-Lite members, not as a blanket skip."""
    camel = [
        sub.pointer
        for sub in iter_subschemas(load_schema(CHART))
        if any(not SNAKE.fullmatch(n) for n in sub.node.get("properties", {}))
    ]
    assert camel and all(_in_chart_spec(CHART, p) for p in camel)
