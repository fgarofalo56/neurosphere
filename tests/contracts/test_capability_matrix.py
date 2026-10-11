"""CapabilityMatrixEntry rules beyond JSON Schema (``check_capability_matrix``).

The schema description names this file: (service, feature, cloud, region, sku) is unique
across a matrix and observed_on is not in the future. availability, ga_status and
authorization_scope stay three separate fields (Clarification 17).
"""

from __future__ import annotations

import copy
from datetime import date

from contract_support import load_schema, schema_errors, valid_cases
from validators import check_capability_matrix

SCHEMA = "deployment/v1/capability-matrix-entry.schema.json"
ROWS = [c.load() for c in valid_cases() if c.schema == SCHEMA]


def test_example_matrix_passes() -> None:
    assert len(ROWS) >= 2
    assert check_capability_matrix(ROWS, today=date(2026, 10, 10)) == []


def test_duplicate_row_is_rejected() -> None:
    assert check_capability_matrix([ROWS[0], copy.deepcopy(ROWS[0])], today=date(2026, 10, 10))
    other_sku = {**ROWS[0], "sku": "OtherSku"}
    assert check_capability_matrix([ROWS[0], other_sku], today=date(2026, 10, 10)) == []


def test_future_observation_is_rejected() -> None:
    row = {**ROWS[0], "observed_on": "2026-10-11"}
    assert check_capability_matrix([row], today=date(2026, 10, 10))
    assert check_capability_matrix([row], today=date(2026, 10, 11)) == []


def test_status_dimensions_are_separate_fields() -> None:
    props = load_schema(SCHEMA)["properties"]
    availability = set(props["availability"]["enum"])
    ga = set(props["ga_status"]["enum"])
    scope = set(props["authorization_scope"]["items"]["enum"])
    assert {"availability", "ga_status", "authorization_scope"} <= set(
        load_schema(SCHEMA)["required"]
    )
    assert not (availability - {"unknown"}) & (ga - {"unknown"})
    assert not (ga - {"unknown"}) & (scope - {"unknown"})
    merged = {k: v for k, v in ROWS[0].items() if k not in ("availability", "ga_status")}
    merged["status"] = "available_ga"
    assert schema_errors(SCHEMA, merged)
