"""``HitlService.mark_expired``: the reconcile sweep closes an undecided maker_checker item."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError

from .hitl_helpers import (
    CHECKER,
    CHECKER_ID,
    CONFIRMATION,
    SCOPE_HASH,
    T0,
    build,
    open_insight,
    open_maker_checker,
)


async def test_pending_and_assigned_items_close_as_expired_and_are_audited() -> None:
    h = build()
    pending = await open_maker_checker(h)
    closed = await h.service.mark_expired(pending.item_id, T0, correlation_id="corr-rec-1")
    assert closed.state_name == "expired"
    other = await open_maker_checker(h)
    await h.service.assign(
        other.item_id, None, CHECKER_ID, T0, by=CHECKER, scope_hash=SCOPE_HASH, correlation_id="c"
    )
    unassigned = await h.service.mark_expired(other.item_id, T0, correlation_id="corr-rec-2")
    assert unassigned.state_name == "expired"
    assert unassigned.assignee_principal_id is None and unassigned.assignee is None
    ops = [(r["operation"], r["kind"]) for r in await h.records()]
    assert ("hitl.review.expired", "before") in ops
    assert ("hitl.review.expired", "after") in ops


async def test_decided_or_insight_items_are_refused_and_left_unchanged() -> None:
    h = build()
    item = await open_maker_checker(h)
    await h.service.decide(
        item.item_id,
        CHECKER_ID,
        CHECKER,
        "approved",
        "ok",
        CONFIRMATION,
        T0,
        "corr-dec-1",
        scope_hash=SCOPE_HASH,
    )
    with pytest.raises(StaleVersionError):
        await h.service.mark_expired(item.item_id, T0, correlation_id="corr-rec-3")
    found = await h.service.get(item.item_id)
    assert found is not None and found.state_name == "approved"
    insight = await open_insight(h)
    with pytest.raises(InvalidSchemaError):
        await h.service.mark_expired(insight.item_id, T0, correlation_id="corr-rec-4")
    denied = [r for r in await h.records() if r["kind"] == "denied"]
    assert len(denied) == 2
