"""Human-label ingestion: validation, conflicts, consensus."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import (
    HumanLabelRecord,
    LabelSource,
    ingest_labels,
)
from pydantic import ValidationError

T = datetime(2026, 10, 1, tzinfo=UTC)


def rec(
    item: str = "i1", labeler: str = "l1", value: float = 1.0, version: str = "v1"
) -> HumanLabelRecord:
    return HumanLabelRecord(
        item_id=item,
        dimension="groundedness",
        label_set_version=version,
        value=value,
        labeler=labeler,
        labelled_at=T,
    )


def test_ingest_keeps_multiple_labelers_and_majority_consensus() -> None:
    ls = ingest_labels(
        [rec(labeler="a", value=1), rec(labeler="b", value=1), rec(labeler="c", value=0)]
    )
    assert ls.label_set_version == "v1"
    assert len(ls.records) == 3
    assert ls.consensus("i1", "groundedness") == 1.0
    assert ls.labeler_count("i1", "groundedness") == 3


def test_tie_has_no_consensus() -> None:
    ls = ingest_labels([rec(labeler="a", value=1), rec(labeler="b", value=0)])
    assert ls.consensus("i1", "groundedness") is None
    assert ls.consensus_map("groundedness") == {}


def test_unknown_item_or_dimension_is_none() -> None:
    ls = ingest_labels([rec()])
    assert ls.consensus("zzz", "groundedness") is None
    assert ls.consensus("i1", "safety") is None


def test_same_labeler_conflict_rejected() -> None:
    with pytest.raises(InvalidSchemaError) as exc:
        ingest_labels([rec(value=1), rec(value=0)])
    assert exc.value.reason == "conflicting_labels"


def test_identical_duplicate_collapsed() -> None:
    assert len(ingest_labels([rec(), rec()]).records) == 1


def test_same_item_different_dimension_is_not_a_conflict() -> None:
    other = rec(value=0).model_copy(update={"dimension": "safety"})
    assert len(ingest_labels([rec(value=1), other]).records) == 2


def test_mixed_versions_and_empty_rejected() -> None:
    with pytest.raises(InvalidSchemaError) as exc:
        ingest_labels([rec(version="v1"), rec(item="i2", version="v2")])
    assert exc.value.reason == "mixed_label_set_versions"
    with pytest.raises(InvalidSchemaError) as exc2:
        ingest_labels([])
    assert exc2.value.reason == "empty_label_set"


def test_label_source_protocol() -> None:
    class Queue:
        def labels(self) -> Iterable[HumanLabelRecord]:
            return [rec()]

    assert isinstance(Queue(), LabelSource)
    assert len(ingest_labels(Queue()).records) == 1


def test_record_validation() -> None:
    with pytest.raises(ValidationError):
        rec(version="bad version!")
    with pytest.raises(ValidationError):
        HumanLabelRecord(
            item_id="i1",
            dimension="groundedness",
            label_set_version="v1",
            value=1,
            labeler="l1",
            labelled_at=datetime(2026, 1, 1),  # naive
        )
    with pytest.raises(ValidationError):
        rec(value=float("nan"))
