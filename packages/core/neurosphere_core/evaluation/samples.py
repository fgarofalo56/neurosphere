"""PRP-16 round 2 item 14: the calibration-review context of an ``evaluation_dispute`` item.

A HITL ``ReviewItem`` carries only an opaque ``subject_ref``. A :class:`CalibrationSample` is the
record, keyed by that ``subject_ref``, that tells a reviewer what the item is: the dataset item, the
dimension, the judge's verdict and the judge/rubric versions, plus a BOUNDED, already-redacted
snapshot of the item payload.

The payload is never stored for restricted or unclassified items (null classification fails closed
to restricted), and never when its canonical JSON exceeds :data:`MAX_PAYLOAD_BYTES`; in both cases
``payload`` is null, ``payload_withheld`` is true and ``withheld_reason`` says why.

Semantics of the review item: it asserts "the judge's verdict on this item is wrong". APPROVE = the
judge was wrong, REJECT = the judge was right.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.evaluation.registry import normalize_classification

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "WITHHELD_RESTRICTED",
    "WITHHELD_TOO_LARGE",
    "CalibrationSample",
    "build_calibration_sample",
    "snapshot_payload",
]

MAX_PAYLOAD_BYTES: Final = 8 * 1024
WITHHELD_RESTRICTED: Final = "restricted"
WITHHELD_TOO_LARGE: Final = "too_large"
WITHHELD_UNAVAILABLE: Final = "unavailable"

Cloud = Literal["commercial", "government"]


class CalibrationSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_ref: str = Field(min_length=1, max_length=512)
    cloud: Cloud
    customer_id: str = Field(pattern=r"^[a-z0-9._-]{1,128}$")
    domain_id: str = Field(min_length=1, max_length=512)
    dataset_id: str | None = Field(default=None, max_length=256)
    dataset_version: str | None = Field(default=None, max_length=256)
    item_id: str = Field(min_length=1, max_length=512)
    dimension: str = Field(min_length=1, max_length=64)
    classification: str | None = Field(default=None, max_length=64)
    judge_config_id: str = Field(min_length=1, max_length=512)
    judge_config_version: str = Field(min_length=1, max_length=256)
    value: float
    rubric_id: str = Field(min_length=1, max_length=256)
    rubric_version: str = Field(min_length=1, max_length=256)
    opened_at: AwareDatetime
    payload: dict[str, Any] | None = None
    payload_withheld: bool = False
    withheld_reason: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _payload_rules(self) -> Self:
        restricted = normalize_classification(self.classification) == "restricted"
        if self.payload is not None:
            if restricted:
                raise ValueError("restricted or unclassified samples never carry a payload")
            if self.payload_withheld or self.withheld_reason is not None:
                raise ValueError("a sample with a payload is not withheld")
            if len(_canonical(self.payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
                raise ValueError("payload exceeds the size cap")
        elif not self.payload_withheld or not self.withheld_reason:
            raise ValueError("a sample without a payload must say it is withheld and why")
        return self


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def snapshot_payload(
    classification: str | None, payload: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """``(payload, withheld, reason)``: fail closed on classification, then on size."""
    if normalize_classification(classification) == "restricted":
        return None, True, WITHHELD_RESTRICTED
    if payload is None:
        return None, True, WITHHELD_UNAVAILABLE
    try:
        size = len(_canonical(payload).encode("utf-8"))
    except (TypeError, ValueError):
        return None, True, WITHHELD_UNAVAILABLE
    if size > MAX_PAYLOAD_BYTES:
        return None, True, WITHHELD_TOO_LARGE
    return json.loads(_canonical(payload)), False, None


def build_calibration_sample(
    *,
    subject_ref: str,
    cloud: Cloud,
    customer_id: str,
    domain_id: str,
    dataset_id: str | None,
    dataset_version: str | None,
    item_id: str,
    dimension: str,
    classification: str | None,
    judge_config_id: str,
    judge_config_version: str,
    value: float,
    rubric_id: str,
    rubric_version: str,
    opened_at: datetime,
    payload: dict[str, Any] | None,
) -> CalibrationSample:
    """Build a sample, applying the payload bounds (restricted / unclassified / oversized)."""
    snapshot, withheld, reason = snapshot_payload(classification, payload)
    return CalibrationSample(
        subject_ref=subject_ref,
        cloud=cloud,
        customer_id=customer_id,
        domain_id=domain_id,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        item_id=item_id,
        dimension=dimension,
        classification=classification,
        judge_config_id=judge_config_id,
        judge_config_version=judge_config_version,
        value=value,
        rubric_id=rubric_id,
        rubric_version=rubric_version,
        opened_at=opened_at,
        payload=snapshot,
        payload_withheld=withheld,
        withheld_reason=reason,
    )
