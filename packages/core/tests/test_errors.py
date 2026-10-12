"""Exception taxonomy is cross-checked against the PRP-01 contract table and model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.errors.v1.problem_details import ProblemDetails
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
    UnauthorizedError,
    ValidationIssue,
)
from pydantic import ValidationError

_TABLE = Path(__file__).resolve().parents[2] / "contracts/schemas/errors/v1/error-codes.json"

_CLASSES: dict[str, type[NeuroSphereError]] = {
    "unauthorized": UnauthorizedError,
    "forbidden": ForbiddenError,
    "capability_unavailable": CapabilityUnavailableError,
    "stale_version": StaleVersionError,
    "rate_limited": RateLimitedError,
    "invalid_schema": InvalidSchemaError,
    "dependency_transient": DependencyTransientError,
}


def _rows() -> list[dict[str, object]]:
    return json.loads(_TABLE.read_text(encoding="utf-8"))["codes"]


def test_every_contract_code_has_exactly_one_class() -> None:
    assert {r["code"] for r in _rows()} == set(_CLASSES)


@pytest.mark.parametrize("row", _rows(), ids=lambda r: str(r["code"]))
def test_status_retryable_title_match_contract(row: dict[str, object]) -> None:
    cls = _CLASSES[str(row["code"])]
    assert cls.code == row["code"]
    assert cls.http_status == row["http_status"]
    assert cls.retryable is row["retryable"]
    assert cls.title == row["title"]
    assert cls.http_status in row["allowed_http_statuses"]  # type: ignore[operator]


def _make(cls: type[NeuroSphereError]) -> NeuroSphereError:
    if cls is CapabilityUnavailableError:
        return CapabilityUnavailableError("not_available_in_cloud", "no")
    if cls is RateLimitedError:
        return RateLimitedError(30)
    if cls is InvalidSchemaError:
        return InvalidSchemaError("bad", errors=[ValidationIssue("/a/b", "required")])
    return cls("detail")


@pytest.mark.parametrize("code", sorted(_CLASSES))
def test_render_validates_against_contract_model(code: str) -> None:
    body = _make(_CLASSES[code]).to_problem_details("corr-1", instance="urn:req:1")
    assert isinstance(body, ProblemDetails)
    assert body.code == code
    # Round trip through the strict contract model.
    ProblemDetails.model_validate(body.model_dump(mode="json", exclude_none=True))


def test_dependency_transient_502_variant() -> None:
    exc = DependencyTransientError("bad upstream", upstream_invalid=True, retry_after_seconds=5)
    assert exc.status == 502
    assert exc.to_problem_details("c").status == 502
    assert DependencyTransientError().status == 503


def test_contract_rules_enforced_at_render() -> None:
    # reason is mandatory for capability_unavailable
    with pytest.raises(ValidationError):
        CapabilityUnavailableError("Not Snake Case").to_problem_details("c")
    # retry_after_seconds forbidden on non-retryable codes
    with pytest.raises(ValueError, match="retry_after_seconds"):
        _ = ForbiddenError(retry_after_seconds=3)
    # bad correlation id
    with pytest.raises(ValidationError):
        UnauthorizedError().to_problem_details("bad id with spaces")


def test_rate_limited_requires_retry_after() -> None:
    factory: Any = RateLimitedError  # deliberately called without its required argument
    with pytest.raises(TypeError):
        _ = factory()
    assert RateLimitedError(7).to_problem_details("c").retry_after_seconds == 7
