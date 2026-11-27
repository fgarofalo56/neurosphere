"""Mappers: HITL notification -> outbox event, violation event -> outbox event. Ids only."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.governance.policy.events import ExceptionDecidedEvent, ViolationEvent
from neurosphere_core.hitl import Notification
from neurosphere_core.notifications import EVENT_CLASSES, NotificationEvent
from neurosphere_core.notifications.hitl import OutboxNotifier, event_for_notification
from neurosphere_core.notifications.violations import ViolationNotificationSink

from .helpers import CUSTOMER, DOMAIN_A, Rig

ITEM = "66666666-6666-4666-8666-666666666666"


def _notification(event: str = "review_assigned", **kw: Any) -> Notification:
    data: dict[str, Any] = {
        "notification_id": "55555555-5555-4555-8555-555555555555",
        "event": event,
        "review_item_id": ITEM,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN_A,
        "recipient_ref": "p-checker",
        "escalation_level": 0,
        "correlation_id": "corr-1",
    }
    data.update(kw)
    return Notification.model_validate(data)


@pytest.mark.parametrize(
    ("hitl_event", "event_class", "severity"),
    [
        ("review_assigned", "hitl_item_assigned", "medium"),
        ("assignment_timed_out", "hitl_item_expiring", "medium"),
        ("review_escalated", "hitl_item_escalated", "high"),
        ("escalation_capped", "hitl_item_escalated", "high"),
        ("review_expired", "hitl_item_expiring", "high"),
    ],
)
def test_every_hitl_event_maps_to_a_contract_class(
    hitl_event: str, event_class: str, severity: str
) -> None:
    event = event_for_notification(_notification(hitl_event))
    assert event.event_class == event_class
    assert event.event_class in EVENT_CLASSES
    assert event.severity == severity
    assert event.domain_id == DOMAIN_A
    assert event.subject.entity_type == "review_item"
    assert event.subject.canonical_id.endswith(ITEM)
    assert event.link.startswith("/review/item?") and ITEM in event.link
    assert event.title and len(event.title) <= 160


def test_the_dedup_key_separates_assignee_and_escalation_step() -> None:
    a = event_for_notification(_notification("review_escalated", escalation_level=1))
    b = event_for_notification(_notification("review_escalated", escalation_level=2))
    c = event_for_notification(_notification("review_assigned", recipient_ref="p-other"))
    d = event_for_notification(_notification("review_assigned", recipient_ref="p-checker"))
    assert len({a.dedup_key, b.dedup_key, c.dedup_key, d.dedup_key}) == 4
    assert (
        a.dedup_key
        == event_for_notification(_notification("review_escalated", escalation_level=1)).dedup_key
    )


async def test_outbox_notifier_is_the_outbox_channel_and_queues_per_subscription() -> None:
    rig = Rig()
    await rig.add_channel("ch-1", DOMAIN_A)
    await rig.add_subscription("sub-1", "ch-1", DOMAIN_A, event_classes=("hitl_item_assigned",))
    from .helpers import OWNER

    rig.grants.grant(OWNER, CUSTOMER, DOMAIN_A, "data.read")
    notifier = OutboxNotifier(rig.publisher)
    assert notifier.channel == "outbox"
    first = await notifier.send(_notification())
    second = await notifier.send(_notification())  # duplicate inside the window
    assert first.status == second.status == "recorded"
    assert first.audit_id != "none"
    assert second.audit_id == "none"
    assert len(await rig.store.list_deliveries(CUSTOMER)) == 1


def _violation(event_class: str = "policy_violation_opened", severity: str = "high") -> Any:
    return ViolationEvent(
        event_class=event_class,  # type: ignore[arg-type]
        cloud="commercial",
        customer_id=CUSTOMER,
        domain_id=DOMAIN_A,
        violation_id="v-1",
        policy_id="pii-guard",
        policy_version=3,
        rule_id="pii-read",
        subject_id=f"commercial:{CUSTOMER}:foundry:agent:reader",
        severity=severity,
        correlation_id="corr-1",
    )


class _Capture:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    async def publish(self, event: NotificationEvent) -> list[Any]:
        self.events.append(event)
        return []


async def test_violation_sink_maps_the_three_event_kinds() -> None:
    capture = _Capture()
    sink = ViolationNotificationSink(capture)  # type: ignore[arg-type]
    await sink.opened(_violation("policy_violation_opened"))
    await sink.resolved(_violation("policy_violation_resolved"))
    await sink.exception_decided(
        ExceptionDecidedEvent(
            cloud="commercial",
            customer_id=CUSTOMER,
            domain_id=DOMAIN_A,
            exception_id="e-1",
            violation_id="v-1",
            policy_id="pii-guard",
            rule_id="pii-read",
            subject_id=f"commercial:{CUSTOMER}:foundry:agent:reader",
            status="approved",
            correlation_id="corr-2",
        )
    )
    assert [e.event_class for e in capture.events] == [
        "policy_violation_opened",
        "policy_violation_resolved",
        "policy_exception_decided",
    ]
    assert all(e.event_class in EVENT_CLASSES for e in capture.events)
    opened, resolved, decided = capture.events
    assert opened.severity == "high"
    assert opened.dedup_key != resolved.dedup_key
    assert opened.subject.entity_type == "policy_violation"
    assert decided.subject.entity_type == "policy_exception"
    assert "v-1" in opened.link and "pii-guard" not in opened.link
    for event in capture.events:
        assert event.dedup_window_seconds and event.dedup_window_seconds >= 3600


async def test_an_unknown_severity_falls_back_to_medium() -> None:
    capture = _Capture()
    await ViolationNotificationSink(capture).opened(_violation(severity="bogus"))  # type: ignore[arg-type]
    assert capture.events[0].severity == "medium"
