"""CostRecord.tags (#190 item 1, PRP-37 item 3).

The ledger keeps the source's cost allocation tags (``nscostcenter`` mapped to
``cost_center`` by PRP-46 ingest): at most 16 entries, lowercase keys, values of 1 to 128
characters, the reserved ``cost_center`` key in the Grant ``cost_center`` grammar. Records
without tags stay valid. The entry count and the cost_center rule are not carried by the
generated Pydantic model (ADR-0004 projection), so they are pinned here against JSON Schema
and ``validate_cost_tags``.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors
from pydantic import ValidationError
from validators import validate_cost_tags

COST = "cost/v1/cost-record.schema.json"
EXAMPLES = SCHEMA_ROOT / "cost" / "v1" / "examples" / "valid"


def _record(**tags: str) -> dict[str, Any]:
    record = load_json(EXAMPLES / "cost-record.invoiced-credit.json")
    record["tags"] = dict(tags)
    return record


def test_cost_center_tag_validates() -> None:
    record = _record(cost_center="cc-1001")
    assert schema_errors(COST, record) == []
    model = model_for(COST).model_validate(record)
    assert model.model_dump(mode="json", exclude_unset=True)["tags"] == {"cost_center": "cc-1001"}
    assert validate_cost_tags(record["tags"]) == []


def test_records_without_tags_still_validate() -> None:
    for path in sorted(EXAMPLES.glob("cost-record.*.json")):
        record = load_json(path)
        untagged = {k: v for k, v in record.items() if k != "tags"}
        assert schema_errors(COST, untagged) == [], path.name
        assert schema_errors(COST, {**untagged, "tags": None}) == [], path.name
        assert model_for(COST).model_validate(untagged).tags is None


def test_more_than_sixteen_entries_rejected() -> None:
    record = _record(**{f"k{i}": "v" for i in range(17)})
    assert any(e.validator == "maxProperties" for e in _tree(record))
    assert validate_cost_tags(record["tags"])
    assert schema_errors(COST, _record(**{f"k{i}": "v" for i in range(16)})) == []


@pytest.mark.parametrize("key", ["CostCenter", "1team", "team name", "a" * 64, "_x", "tëam"])
def test_bad_keys_rejected(key: str) -> None:
    record = _record(**{key: "v"})
    assert schema_errors(COST, record)
    with pytest.raises(ValidationError):
        model_for(COST).model_validate(record)


@pytest.mark.parametrize("value", ["", "x" * 129])
def test_value_bounds(value: str) -> None:
    record = _record(team=value)
    assert schema_errors(COST, record)
    with pytest.raises(ValidationError):
        model_for(COST).model_validate(record)
    assert schema_errors(COST, _record(team="x" * 128)) == []


@pytest.mark.parametrize("value", ["cc 1001", "-cc", "cc@1001"])
def test_cost_center_uses_grant_pattern(value: str) -> None:
    record = _record(cost_center=value)
    assert any(e.validator == "pattern" for e in _tree(record))
    assert validate_cost_tags(record["tags"])


def test_non_string_values_rejected() -> None:
    record = _record()
    record["tags"] = {"team": 7}
    assert schema_errors(COST, record)
    record["tags"] = {"team": {"nested": "x"}}
    assert schema_errors(COST, record)


def test_cost_center_pattern_equals_grant_and_admin_grammar() -> None:
    grant = load_schema("catalog/v1/grant.schema.json")["properties"]["cost_center"]["anyOf"][0]
    tags = load_schema(COST)["$defs"]["tags"]
    reserved = tags["allOf"][0]["then"]["properties"]["cost_center"]["pattern"]
    assert reserved == grant["pattern"]
    admin = load_schema("admin/v1/common.schema.json")["$defs"]["cost_tags"]
    stripped = {k: v for k, v in tags.items() if k not in ("title", "description")}
    assert stripped == {k: v for k, v in admin.items() if k != "description"}


def test_tags_is_optional() -> None:
    assert "tags" not in load_schema(COST)["required"]


def _tree(record: dict[str, Any]) -> list[Any]:
    from contract_support import iter_error_tree

    return list(iter_error_tree(schema_errors(COST, copy.deepcopy(record))))
