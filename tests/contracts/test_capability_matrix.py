"""CapabilityMatrixEntry rules beyond JSON Schema (``check_capability_matrix``).

The schema description names this file: (service, feature, cloud, region, sku) is unique
across a matrix and observed_on is not in the future. availability, ga_status and
authorization_scope stay three separate fields (Clarification 17).
"""

from __future__ import annotations

import copy
from datetime import date

from contract_support import load_schema, schema_errors, valid_cases
from validators import capability_region_covers, capability_row_id, check_capability_matrix

SCHEMA = "deployment/v1/capability-matrix-entry.schema.json"
ROWS = [c.load() for c in valid_cases() if c.schema == SCHEMA]


def test_example_matrix_passes() -> None:
    assert len(ROWS) >= 2
    assert check_capability_matrix(ROWS, today=date(2026, 10, 10)) == []


def test_duplicate_row_is_rejected() -> None:
    assert check_capability_matrix([ROWS[0], copy.deepcopy(ROWS[0])], today=date(2026, 10, 10))
    other_sku = {**ROWS[0], "sku": "OtherSku"}
    other_sku["id"] = capability_row_id(other_sku)
    assert check_capability_matrix([ROWS[0], other_sku], today=date(2026, 10, 10)) == []


def test_future_observation_is_rejected() -> None:
    row = {**ROWS[0], "observed_on": "2026-10-11"}
    assert check_capability_matrix([row], today=date(2026, 10, 10))
    assert check_capability_matrix([row], today=date(2026, 10, 11)) == []


def test_status_dimensions_are_separate_fields() -> None:
    props = load_schema(SCHEMA)["properties"]
    availability = set(props["availability"]["enum"])
    ga = set(props["ga_status"]["enum"])
    scope = props["authorization_scope"]
    assert scope["type"] == "string"
    assert {"availability", "ga_status", "authorization_scope"} <= set(
        load_schema(SCHEMA)["required"]
    )
    assert availability == {"available", "preview", "unavailable", "unverified"}
    assert ga == {"ga", "preview", "not_applicable", "unverified"}
    merged = {k: v for k, v in ROWS[0].items() if k not in ("availability", "ga_status")}
    merged["status"] = "available_ga"
    assert schema_errors(SCHEMA, merged)


GOV = next(r for r in ROWS if r["id"].endswith(".government.usgovvirginia.standard"))


def _row(**over: object) -> dict[str, object]:
    return {**GOV, **over}


def test_every_example_row_id_matches_convention() -> None:
    for row in ROWS:
        assert row["id"] == capability_row_id(row)


def test_id_convention_examples() -> None:
    assert capability_row_id(_row(sku=None)) == (
        "azure_openai.model_gpt_4o.government.usgovvirginia.any"
    )
    assert capability_row_id(_row(sku="Pay As You Go (v2)")) == (
        "azure_openai.model_gpt_4o.government.usgovvirginia.pay-as-you-go-v2"
    )
    assert capability_row_id(_row(region="*", sku=None)) == (
        "azure_openai.model_gpt_4o.government.any.any"
    )


def test_id_must_equal_derived_convention() -> None:
    drifted = _row(id="azure_openai.model_gpt_4o.government.usgovvirginia.premium")
    assert any("derived" in p for p in check_capability_matrix([drifted], today=date(2026, 10, 10)))


def test_ids_must_be_unique() -> None:
    twin = _row(sku="Other")
    problems = check_capability_matrix([GOV, twin], today=date(2026, 10, 10))
    assert any("duplicate capability row id" in p for p in problems)


def test_id_is_required_and_lowercase() -> None:
    assert schema_errors(SCHEMA, {k: v for k, v in ROWS[0].items() if k != "id"})
    assert schema_errors(SCHEMA, _row(id="Azure_OpenAI.model.government.usgovvirginia.any"))
    assert schema_errors(SCHEMA, _row(id="ab.c"))
    assert schema_errors(SCHEMA, _row()) == []


def test_new_enums_reject_old_values() -> None:
    for old in ("limited", "unknown"):
        assert schema_errors(SCHEMA, _row(availability=old))
    for old in ("public_preview", "private_preview", "deprecated", "retired", "unknown"):
        assert schema_errors(SCHEMA, _row(ga_status=old))
    for new in ("available", "preview", "unavailable", "unverified"):
        assert schema_errors(SCHEMA, _row(availability=new)) == []
    for new in ("ga", "preview", "not_applicable", "unverified"):
        assert schema_errors(SCHEMA, _row(ga_status=new)) == []


def test_authorization_scope_is_a_citation_string() -> None:
    assert schema_errors(SCHEMA, _row(authorization_scope="none_claimed")) == []
    assert (
        schema_errors(
            SCHEMA,
            _row(authorization_scope="FedRAMP High assessment in progress; not authorized"),
        )
        == []
    )
    assert schema_errors(SCHEMA, _row(authorization_scope=""))
    assert schema_errors(SCHEMA, _row(authorization_scope="x" * 501))
    assert schema_errors(SCHEMA, _row(authorization_scope=["fedramp_high"]))


def test_region_wildcard_is_allowed_for_both_clouds_and_sku_has_none() -> None:
    gov = _row(region="*", sku=None, id="azure_openai.model_gpt_4o.government.any.any")
    assert schema_errors(SCHEMA, gov) == []
    com = _row(
        cloud="commercial",
        region="*",
        sku=None,
        id="azure_openai.model_gpt_4o.commercial.any.any",
    )
    assert schema_errors(SCHEMA, com) == []
    assert check_capability_matrix([gov, com], today=date(2026, 10, 10)) == []
    assert schema_errors(SCHEMA, _row(sku="*"))
    assert schema_errors(SCHEMA, _row(region="**"))
    assert schema_errors(SCHEMA, _row(cloud="commercial", region="usgovvirginia"))


def test_government_wildcard_never_matches_commercial_regions() -> None:
    assert capability_region_covers("government", "*", "government", "usgovvirginia")
    assert capability_region_covers("government", "*", "government", "usdodeast")
    assert not capability_region_covers("government", "*", "government", "eastus")
    assert not capability_region_covers("government", "*", "commercial", "eastus")
    assert not capability_region_covers("government", "*", "commercial", "usgovvirginia")
    assert capability_region_covers("commercial", "*", "commercial", "eastus")
    assert not capability_region_covers("commercial", "*", "commercial", "usgovvirginia")
    assert not capability_region_covers("commercial", "*", "government", "usgovvirginia")
    assert capability_region_covers("government", "usgovtexas", "government", "usgovtexas")
    assert not capability_region_covers("government", "usgovtexas", "government", "usgovarizona")
