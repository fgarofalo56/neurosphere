"""Scope rule at publish and delivery time."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import InvalidSchemaError

from .helpers import CUSTOMER, DOMAIN_A, DOMAIN_B, OTHER_OWNER, OWNER, Rig, make_event


async def _rig_two_domains() -> Rig:
    rig = Rig()
    await rig.add_channel("chan-a", DOMAIN_A)
    await rig.add_subscription("sub-a", "chan-a", DOMAIN_A)
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    return rig


async def test_matching_subscription_creates_one_pending_row() -> None:
    rig = await _rig_two_domains()
    rows = await rig.publisher.publish(make_event(DOMAIN_A))
    assert [r.status for r in rows] == ["pending"]
    assert rows[0].channel_id.root == "chan-a"
    assert rows[0].subscription_id.root == "sub-a"


async def test_other_domain_event_leaves_no_trace() -> None:
    rig = await _rig_two_domains()
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_B, "data.read")
    hidden_title = "Quarterly layoffs agent flagged"
    rows = await rig.publisher.publish(
        make_event(DOMAIN_B, title=hidden_title, dedup_key="other-domain-entity")
    )
    assert rows == []
    stored = await rig.store.list_deliveries(CUSTOMER)
    assert stored == []
    assert hidden_title not in repr(rig.store.__dict__)
    assert "other-domain-entity" not in repr(rig.store.__dict__)


async def test_owner_without_read_gets_no_row() -> None:
    rig = Rig()
    await rig.add_channel("chan-a", DOMAIN_A)
    await rig.add_subscription("sub-a", "chan-a", DOMAIN_A)
    assert await rig.publisher.publish(make_event()) == []


@pytest.mark.parametrize(
    "case",
    ["disabled_sub", "disabled_channel", "class", "severity", "audience_no_read"],
)
async def test_non_matching_subscription_makes_no_row(case: str) -> None:
    rig = Rig()
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    await rig.add_channel("chan-a", DOMAIN_A, enabled=case != "disabled_channel")
    kw = {
        "disabled_sub": {"enabled": False},
        "class": {"event_classes": ("hitl_item_escalated",)},
        "severity": {"min_severity": "critical"},
        "audience_no_read": {"roles": ("domain_steward", "security_auditor")},
    }.get(case, {})
    await rig.add_subscription("sub-a", "chan-a", DOMAIN_A, **kw)
    assert await rig.publisher.publish(make_event(severity="high")) == []


async def test_unknown_event_class_is_refused() -> None:
    rig = await _rig_two_domains()
    with pytest.raises(InvalidSchemaError) as caught:
        await rig.publisher.publish(make_event(event_class="made_up_event"))
    assert caught.value.reason == "unknown_event_class"


async def test_recheck_error_fails_closed_at_publish() -> None:
    rig = await _rig_two_domains()
    rig.grants.fail_with(RuntimeError("policy store down"))
    assert await rig.publisher.publish(make_event()) == []


async def test_delivery_recheck_allows_then_suppresses_when_owner_loses_read() -> None:
    rig = await _rig_two_domains()
    (row,) = await rig.publisher.publish(make_event())
    decision = await rig.resolver.recheck_for_delivery(row)
    assert decision.allowed and decision.channel is not None
    rig.grants.revoke(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    decision = await rig.resolver.recheck_for_delivery(row)
    assert (decision.allowed, decision.suppress, decision.reason) == (False, True, "scope")


async def test_delivery_recheck_suppresses_when_subscription_or_channel_gone() -> None:
    rig = await _rig_two_domains()
    (row,) = await rig.publisher.publish(make_event())
    sub = await rig.registry.subscription(CUSTOMER, "sub-a")
    assert sub is not None
    await rig.admin.retire(
        CUSTOMER, "notification_subscription", "sub-a", if_match=sub.etag, updated_by=OWNER
    )
    decision = await rig.resolver.recheck_for_delivery(row)
    assert (decision.suppress, decision.reason) == (True, "scope")


async def test_delivery_recheck_error_neither_sends_nor_suppresses() -> None:
    rig = await _rig_two_domains()
    (row,) = await rig.publisher.publish(make_event())
    rig.grants.fail_with(RuntimeError("down"))
    decision = await rig.resolver.recheck_for_delivery(row)
    assert (decision.allowed, decision.suppress) == (False, False)


async def test_owner_is_the_last_writer() -> None:
    rig = Rig()
    await rig.add_channel("chan-a", DOMAIN_A)
    await rig.add_subscription("sub-a", "chan-a", DOMAIN_A, owner=OTHER_OWNER)
    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    assert await rig.publisher.publish(make_event()) == []
    rig.grants.grant(OTHER_OWNER, CUSTOMER, DOMAIN_A, "data.read")
    assert len(await rig.publisher.publish(make_event())) == 1
