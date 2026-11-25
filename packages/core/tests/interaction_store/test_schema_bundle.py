"""PRP-102 item 4: the vendored RedactedContent schema equals a fresh bundle of the contracts."""

from __future__ import annotations

import json
from importlib import resources

from jsonschema import Draft202012Validator
from neurosphere_core.interactions.store import redacted_content_schema

from .schema_bundle import BUNDLE_PATH, SCHEMAS_ROOT, build_bundle, render


def test_vendored_bundle_matches_the_contract_schemas() -> None:
    rebuilt = build_bundle(SCHEMAS_ROOT)
    vendored = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    assert vendored == rebuilt, (
        "redacted_content.schema.json drifted from packages/contracts/schemas; regenerate with "
        "python packages/core/tests/interaction_store/schema_bundle.py --write"
    )
    assert BUNDLE_PATH.read_text(encoding="utf-8") == render(rebuilt)


def test_bundle_is_self_contained_and_valid_2020_12() -> None:
    schema = redacted_content_schema()
    Draft202012Validator.check_schema(schema)
    refs: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str):
                    refs.append(v)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert refs and all(r.startswith("#/") for r in refs)
    assert "not" in schema["$defs"]["secret_free_text"]


def test_bundle_is_package_data() -> None:
    resource = resources.files("neurosphere_core.interactions").joinpath(
        "redacted_content.schema.json"
    )
    assert resource.is_file()
