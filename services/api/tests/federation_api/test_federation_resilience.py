"""PRP-21 round 2 item 2: one bad cell never denies the whole summary; windows and cache."""

from datetime import timedelta
from typing import Any

import pytest
from neurosphere_api.federation import SummaryCache
from neurosphere_api.federation.cache import HARD_MAX_TTL_SECONDS
from neurosphere_api.federation.models import MergedSummary
from neurosphere_core.errors import ForbiddenError, UnauthorizedError
from neurosphere_workers.federation import CellSummary, DomainSummary
from test_federation_scope import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    BOUNDARY,
    CELL_A,
    CELL_B,
    CUSTOMER,
    FINANCE,
    HR,
    NOW,
    FixedClient,
    build,
)


def _answer(**overrides: Any) -> CellSummary:
    base: dict[str, Any] = {
        "cell_id": "cell-b",
        "cloud": "commercial",
        "boundary_id": BOUNDARY,
        "customer_id": CUSTOMER,
        "scope_hash": "sha256:" + "1" * 64,
        "window_start": NOW - timedelta(days=30),
        "window_end": NOW,
        "domains": (DomainSummary(domain_id=HR, request_count=777, complete=True),),
    }
    base.update(overrides)
    return CellSummary(**base)


@pytest.mark.parametrize(
    "mismatch",
    [
        {"cell_id": "cell-z"},
        {"cloud": "government"},
        {"boundary_id": "boundary-9"},
        {"customer_id": "fabrikam"},
    ],
)
def test_mismatched_cell_is_unavailable_and_others_still_merge(mismatch: dict[str, Any]) -> None:
    env = build(overrides={"cell-b": FixedClient(_answer(**mismatch))})
    response = env.get(BOB)
    assert response.status_code == 200
    body = response.json()
    states = {c["cell_id"]: c["state"] for c in body["cells"]}
    assert states == {"cell-a": "ok", "cell-b": "unavailable"}
    assert "777" not in response.text
    assert body["complete"] is False
    assert any(d["domain_id"] == FINANCE for d in body["domains"])  # cell-a still merged


def test_window_is_min_start_and_max_end_across_cells() -> None:
    first = _answer(
        cell_id="cell-a",
        window_start=NOW - timedelta(days=40),
        window_end=NOW - timedelta(days=1),
        domains=(),
    )
    second = _answer(
        window_start=NOW - timedelta(days=10), window_end=NOW + timedelta(days=2), domains=()
    )
    env = build(
        registry_cells=(CELL_A, CELL_B),
        overrides={"cell-a": FixedClient(first), "cell-b": FixedClient(second)},
    )
    merged = MergedSummary.model_validate(env.get(BOB).json())
    assert merged.window_start == first.window_start
    assert merged.window_end == second.window_end


@pytest.mark.parametrize("error", [ForbiddenError("no"), UnauthorizedError("no")])
def test_every_cell_denied_is_403_not_an_empty_200(error: Exception) -> None:
    env = build(overrides={"cell-a": FixedClient(error), "cell-b": FixedClient(error)})
    response = env.get(ALICE)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_put_evicts_oldest_without_rebuilding_the_dict() -> None:
    value = MergedSummary.model_validate(build().get(BOB).json())
    clock = _Clock()
    cache = SummaryCache(10.0, clock=clock, max_entries=2)
    cache.put("a", value)
    entries = cache._entries  # pyright: ignore[reportPrivateUsage]
    clock.now = 1.0
    cache.put("b", value)
    clock.now = 2.0
    cache.put("c", value)  # evicts "a", the oldest, in place
    assert cache._entries is entries  # pyright: ignore[reportPrivateUsage]
    assert cache.get("a") is None
    assert cache.get("b") is value
    assert cache.get("c") is value
    clock.now = 11.5  # "b" expired (11.0), "c" still live (12.0)
    cache.put("d", value)
    assert cache.get("b") is None
    assert cache.get("c") is value


def test_cache_ttl_ceiling_is_configurable_and_capped() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        SummaryCache(400.0)
    assert SummaryCache(400.0, max_ttl_seconds=600.0).ttl_seconds == 400.0
    with pytest.raises(ValueError, match="max_ttl_seconds"):
        SummaryCache(10.0, max_ttl_seconds=HARD_MAX_TTL_SECONDS + 1)
