from __future__ import annotations

import pytest
from neurosphere_core.paging import Page, PageRequest, TraversalBudget
from pydantic import ValidationError


def test_page_request_defaults_and_bounds() -> None:
    assert PageRequest().page_size == 50
    assert PageRequest(page_size=500).page_size == 500
    for bad in (0, -1, 501):
        with pytest.raises(ValidationError):
            PageRequest(page_size=bad)


@pytest.mark.parametrize("cursor", ["", "a b", "x" * 2049, "a;drop", "a/b"])
def test_bad_cursor_rejected(cursor: str) -> None:
    with pytest.raises(ValidationError):
        PageRequest(cursor=cursor)


def test_extra_fields_forbidden_and_frozen() -> None:
    with pytest.raises(ValidationError):
        PageRequest.model_validate({"page_size": 5, "offset": 1})
    req = PageRequest(cursor="abc_-=.~")
    with pytest.raises(ValidationError):
        req.page_size = 9


def test_page_is_bounded() -> None:
    assert Page[int](items=(1, 2), next_cursor="c1").items == (1, 2)
    with pytest.raises(ValidationError):
        Page[int](items=tuple(range(501)))


@pytest.mark.parametrize(
    "field,low,high",
    [("max_nodes", 1, 100_000), ("max_edges", 1, 500_000), ("max_duration_ms", 1, 60_000)],
)
def test_budget_bounds(field: str, low: int, high: int) -> None:
    assert getattr(TraversalBudget(**{field: low}), field) == low
    assert getattr(TraversalBudget(**{field: high}), field) == high
    for bad in (low - 1, high + 1):
        with pytest.raises(ValidationError):
            TraversalBudget(**{field: bad})


def test_clamp_never_raises_ceiling() -> None:
    ceiling = TraversalBudget(max_nodes=100, max_edges=200, max_duration_ms=300)
    asked = TraversalBudget(max_nodes=10_000, max_edges=50, max_duration_ms=300)
    got = asked.clamp(ceiling)
    assert (got.max_nodes, got.max_edges, got.max_duration_ms) == (100, 50, 300)
