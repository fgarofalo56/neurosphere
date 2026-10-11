"""Error taxonomy (PRP.md section 3, Clarification 14, PRP-01 item 5).

Seven codes with fixed HTTP statuses and retryable flags; capability_unavailable requires a
machine-readable reason; rate_limited requires retry_after_seconds. The data table
(errors/v1/error-codes.json) and the problem-details schema must agree, and the audit
record's denial codes mirror the taxonomy (``validate_denial_codes_match_error_taxonomy``).
"""

from __future__ import annotations

from typing import Any

import pytest
from contract_support import load_schema, schema_errors
from validators import validate_denial_codes_match_error_taxonomy

PROBLEM = "errors/v1/problem-details.schema.json"

EXPECTED = {
    # code: (http statuses, retryable, reason, retry_after_seconds)
    "unauthorized": ([401], False, "optional", "forbidden"),
    "forbidden": ([403], False, "optional", "forbidden"),
    "capability_unavailable": ([409], False, "required", "forbidden"),
    "stale_version": ([409], False, "optional", "forbidden"),
    "rate_limited": ([429], True, "optional", "required"),
    "invalid_schema": ([422], False, "optional", "forbidden"),
    "dependency_transient": ([503, 502], True, "optional", "optional"),
}


def _problem(code: str, status: int, retryable: bool, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "type": "about:blank",
        "title": code.replace("_", " ").capitalize(),
        "status": status,
        "code": code,
        "retryable": retryable,
        "correlation_id": "corr-0001",
        **extra,
    }


def _minimal_valid(code: str) -> dict[str, Any]:
    statuses, retryable, reason, retry_after = EXPECTED[code]
    extra: dict[str, Any] = {}
    if reason == "required":
        extra["reason"] = "region_not_supported"
    if retry_after == "required":
        extra["retry_after_seconds"] = 30
    return _problem(code, statuses[0], retryable, **extra)


def test_table_has_exactly_seven_codes(error_codes: dict[str, Any]) -> None:
    codes = [row["code"] for row in error_codes["codes"]]
    assert codes == list(EXPECTED)
    assert load_schema(PROBLEM)["properties"]["code"]["enum"] == codes


@pytest.mark.parametrize("code", list(EXPECTED))
def test_table_row(code: str, error_codes: dict[str, Any]) -> None:
    row = next(r for r in error_codes["codes"] if r["code"] == code)
    statuses, retryable, reason, retry_after = EXPECTED[code]
    assert row["http_status"] == statuses[0]
    assert row["allowed_http_statuses"] == statuses
    assert row["retryable"] is retryable
    assert row["reason"] == reason
    assert row["retry_after_seconds"] == retry_after


@pytest.mark.parametrize("code", list(EXPECTED))
def test_schema_enforces_status_and_retryable(code: str) -> None:
    statuses, retryable, _, _ = EXPECTED[code]
    assert schema_errors(PROBLEM, _minimal_valid(code)) == []
    for status in statuses:
        assert schema_errors(PROBLEM, {**_minimal_valid(code), "status": status}) == []
    for status in {401, 403, 409, 422, 429, 502, 503} - set(statuses):
        assert schema_errors(PROBLEM, {**_minimal_valid(code), "status": status}), status
    flipped = {**_minimal_valid(code), "retryable": not retryable}
    flipped.pop("retry_after_seconds", None)
    assert schema_errors(PROBLEM, flipped)


def test_capability_unavailable_requires_reason() -> None:
    document = _minimal_valid("capability_unavailable")
    del document["reason"]
    assert any(e.validator == "required" for e in schema_errors(PROBLEM, document))


def test_rate_limited_requires_retry_after() -> None:
    document = _minimal_valid("rate_limited")
    del document["retry_after_seconds"]
    assert any(e.validator == "required" for e in schema_errors(PROBLEM, document))


@pytest.mark.parametrize("code", [c for c, row in EXPECTED.items() if row[3] == "forbidden"])
def test_retry_after_forbidden_on_non_retryable(code: str) -> None:
    assert schema_errors(PROBLEM, {**_minimal_valid(code), "retry_after_seconds": 5})


def test_retry_after_optional_for_dependency_transient() -> None:
    assert (
        schema_errors(PROBLEM, {**_minimal_valid("dependency_transient"), "retry_after_seconds": 5})
        == []
    )


def test_correlation_id_is_required() -> None:
    assert "correlation_id" in load_schema(PROBLEM)["required"]


def test_validate_denial_codes_match_error_taxonomy(error_codes: dict[str, Any]) -> None:
    audit = load_schema("audit/v1/audit-record.schema.json")
    assert validate_denial_codes_match_error_taxonomy(audit, error_codes) == []
    short = {"codes": error_codes["codes"][:-1]}
    assert validate_denial_codes_match_error_taxonomy(audit, short)
