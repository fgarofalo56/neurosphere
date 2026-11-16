"""SubjectPoint documents: round trip, key helpers, health thresholds, backward compatibility."""

from __future__ import annotations

import pytest
from neurosphere_core.aggregates import (
    HEALTH_DEGRADED_ERROR_RATE,
    HEALTH_FAILING_ERROR_RATE,
    Contribution,
    EventFact,
    SubjectMetricsReader,
    SubjectPoint,
    health_for_error_rate,
    subject_series_key,
)
from neurosphere_core.aggregates.models import AGGREGATE_ADAPTER
from neurosphere_core.aggregates.store import InMemoryAggregateStore

from .support import point


def test_round_trip_through_the_discriminated_union() -> None:
    original = point("agent:a-1")
    again = AGGREGATE_ADAPTER.validate_python(original.model_dump(mode="json"))
    assert isinstance(again, SubjectPoint)
    assert again == original


def test_series_keys() -> None:
    assert subject_series_key("agent", "ns:agent:one") == "agent:ns:agent:one"
    assert subject_series_key("model", "Azure_OpenAI", "GPT-4o") == "model:azure_openai/gpt-4o"
    with pytest.raises(ValueError, match="provider and model"):
        subject_series_key("model", "azure_openai")


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (None, "unknown"),
        (0.0, "ok"),
        (0.0499, "ok"),
        (HEALTH_DEGRADED_ERROR_RATE, "degraded"),
        (0.2, "degraded"),
        (HEALTH_FAILING_ERROR_RATE, "failing"),
        (1.0, "failing"),
    ],
)
def test_health_thresholds(rate: float | None, expected: str) -> None:
    assert health_for_error_rate(rate) == expected


def test_old_contribution_without_the_dimension_still_validates() -> None:
    stored = {
        "id": "event-x",
        "customer_id": "c",
        "domain_id": "d",
        "origin": "event",
        "occurred_at": "2026-11-01T10:00:00.000000Z",
        "observed_at": "2026-11-01T10:00:00.000000Z",
        "event": {"duration_ms": 5, "outcome": "success"},
    }
    parsed = Contribution.model_validate(stored)
    assert parsed.event == EventFact(duration_ms=5, outcome="success")
    assert parsed.event is not None
    assert parsed.event.agent_id is None
    assert parsed.event.input_tokens is None


def test_in_memory_store_implements_the_subject_reader() -> None:
    assert isinstance(InMemoryAggregateStore(), SubjectMetricsReader)
