"""PRP-34 item 4: the grant ``x-ns-cost-center`` metric dimension lands on the cost tags."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_connector_azure_monitor.gateway_mapping import (
    COST_CENTER_DIMENSION,
    cost_center_tags,
    map_gateway_row,
)

ROW: dict[str, Any] = {
    "TimeGenerated": "2026-10-29T10:00:00.1234567Z",
    "CorrelationId": "corr-1",
    "ModelName": "gpt-4o",
    "PromptTokens": 10,
    "CompletionTokens": 5,
    "TotalTokens": 15,
}
ARGS: dict[str, Any] = {"cloud": "commercial", "customer_id": "cust-1", "source_id": "apim-poll"}


def test_cost_center_dimension_maps_to_cost_tags() -> None:
    assert COST_CENTER_DIMENSION == "x-ns-cost-center"
    mapped = map_gateway_row({**ROW, COST_CENTER_DIMENSION: "CC-4410"}, **ARGS)
    assert mapped.cost.tags == {"cost_center": "CC-4410"}
    # Absent stays absent: the field is additive and None by default.
    assert map_gateway_row(ROW, **ARGS).cost.tags is None


@pytest.mark.parametrize("value", [None, "", "N/A", "has space", "x" * 129, "-lead"])
def test_default_or_unsafe_cost_center_is_dropped(value: str | None) -> None:
    assert cost_center_tags({COST_CENTER_DIMENSION: value}) is None
