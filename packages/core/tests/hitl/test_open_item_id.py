"""``HitlService.open_item(item_id=...)``: a chosen id; a lost create race is a conflict."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import StaleVersionError

from .hitl_helpers import CUSTOMER, DOMAIN, EDGE, T0, build

ITEM_ID = "7d1f3a4e-2b6c-5d8e-9f01-23456789abcd"


async def _open(harness, **kw):  # type: ignore[no-untyped-def]
    return await harness.service.open_item(
        kind="relationship",
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        subject_ref=EDGE,
        now=T0,
        correlation_id="corr-open-id",
        **kw,
    )


async def test_explicit_item_id_is_used() -> None:
    harness = build()
    item = await _open(harness, item_id=ITEM_ID)
    assert item.item_id == ITEM_ID
    assert (await harness.service.get(ITEM_ID)) is not None


async def test_default_item_id_still_comes_from_the_id_factory() -> None:
    harness = build()
    item = await _open(harness)
    assert item.item_id != ITEM_ID


async def test_second_open_with_the_same_id_is_a_conflict_not_a_second_item() -> None:
    harness = build()
    await _open(harness, item_id=ITEM_ID)
    with pytest.raises(StaleVersionError) as caught:
        await _open(harness, item_id=ITEM_ID)
    assert caught.value.reason == "review_item_exists"
