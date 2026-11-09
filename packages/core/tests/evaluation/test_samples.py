"""CalibrationSample bounds (PRP-16 round 2 item 14): fail-closed payload handling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_core.evaluation.samples import (
    MAX_PAYLOAD_BYTES,
    CalibrationSample,
    build_calibration_sample,
)
from pydantic import ValidationError

T = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def _build(classification: str | None, payload: dict[str, Any] | None) -> CalibrationSample:
    return build_calibration_sample(
        subject_ref="commercial:contoso:evaluation:dispute:abc",
        cloud="commercial",
        customer_id="contoso",
        domain_id="commercial:contoso:catalog:domain:finance",
        dataset_id="ds",
        dataset_version="1",
        item_id="i1",
        dimension="groundedness",
        classification=classification,
        judge_config_id="judge",
        judge_config_version="1+2",
        value=0.0,
        rubric_id="r",
        rubric_version="1",
        opened_at=T,
        payload=payload,
    )


def test_internal_payload_is_kept() -> None:
    sample = _build("internal", {"a": [1, 2]})
    assert sample.payload == {"a": [1, 2]}
    assert sample.payload_withheld is False
    assert sample.withheld_reason is None


@pytest.mark.parametrize("classification", [None, "restricted", "not-a-class"])
def test_restricted_and_unclassified_never_keep_a_payload(classification: str | None) -> None:
    sample = _build(classification, {"secret": "x"})
    assert sample.payload is None
    assert sample.payload_withheld is True
    assert sample.withheld_reason == "restricted"


def test_oversized_payload_is_withheld_not_truncated() -> None:
    sample = _build("internal", {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)})
    assert sample.payload is None
    assert sample.payload_withheld is True
    assert sample.withheld_reason == "too_large"


def test_payload_at_the_cap_is_kept() -> None:
    overhead = len('{"b":""}')
    sample = _build("internal", {"b": "x" * (MAX_PAYLOAD_BYTES - overhead)})
    assert sample.payload is not None


def test_model_rejects_a_restricted_sample_with_a_payload() -> None:
    good = _build("internal", {"a": 1})
    with pytest.raises(ValidationError):
        CalibrationSample.model_validate({**good.model_dump(), "classification": "restricted"})


def test_model_rejects_a_missing_payload_that_is_not_marked_withheld() -> None:
    good = _build("internal", {"a": 1})
    with pytest.raises(ValidationError):
        CalibrationSample.model_validate({**good.model_dump(), "payload": None})
