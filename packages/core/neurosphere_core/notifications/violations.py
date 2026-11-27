"""``ViolationNotificationSink``: binds PRP-105's ``ViolationEventSink`` to the notification outbox.

``opened`` -> ``policy_violation_opened``, ``resolved`` -> ``policy_violation_resolved``,
``exception_decided`` -> ``policy_exception_decided``. Each event holds ids, the policy id, the
severity and an application-relative link to the violation: no evidence value, no rule parameter.

Dedup: the key is the violation (or exception) id plus the decision, and the window is a day, so a
repeated tick over the same open violation publishes once. The sink never fails the run: the
evaluator already logs a raising sink, and this one logs by reason code first.
"""

from __future__ import annotations

import logging
from typing import Final
from urllib.parse import urlencode

from neurosphere_contracts.actions.v1.target_ref import TargetRef

from neurosphere_core.governance.policy.events import ExceptionDecidedEvent, ViolationEvent
from neurosphere_core.governance.policy.ids import exception_canonical_id, violation_canonical_id
from neurosphere_core.notifications.models import NotificationEvent
from neurosphere_core.notifications.publisher import NotificationPublisher

__all__ = ["ViolationNotificationSink"]

_LOG: Final = logging.getLogger(__name__)
DEDUP_WINDOW_SECONDS: Final = 86_400
_SEVERITIES: Final = frozenset({"low", "medium", "high", "critical"})
_EXCEPTION_SEVERITY: Final = "medium"
_TITLES: Final[dict[str, str]] = {
    "policy_violation_opened": "Policy violation opened",
    "policy_violation_resolved": "Policy violation resolved",
}


def _link(violation_id: str | None, domain_id: str) -> str:
    query = {"domain_id": domain_id}
    if violation_id is not None:
        query["violation_id"] = violation_id
    return "/governance/violations?" + urlencode(query)


class ViolationNotificationSink:
    def __init__(self, publisher: NotificationPublisher) -> None:
        self._publisher = publisher

    async def opened(self, event: ViolationEvent) -> None:
        await self._violation(event)

    async def resolved(self, event: ViolationEvent) -> None:
        await self._violation(event)

    async def exception_decided(self, event: ExceptionDecidedEvent) -> None:
        await self._publish(
            NotificationEvent(
                event_class="policy_exception_decided",
                customer_id=event.customer_id,
                cloud=event.cloud,
                domain_id=event.domain_id,
                subject=TargetRef(
                    canonical_id=exception_canonical_id(
                        event.cloud, event.customer_id, event.exception_id
                    ),
                    entity_type="policy_exception",
                ),
                title=f"Policy exception {event.status}",
                severity=_EXCEPTION_SEVERITY,
                link=_link(event.violation_id, event.domain_id),
                correlation_id=event.correlation_id,
                dedup_key=f"exception:{event.exception_id}:{event.status}",
                dedup_window_seconds=DEDUP_WINDOW_SECONDS,
            )
        )

    async def _violation(self, event: ViolationEvent) -> None:
        severity = event.severity if event.severity in _SEVERITIES else "medium"
        await self._publish(
            NotificationEvent(
                event_class=event.event_class,
                customer_id=event.customer_id,
                cloud=event.cloud,
                domain_id=event.domain_id,
                subject=TargetRef(
                    canonical_id=violation_canonical_id(
                        event.cloud, event.customer_id, event.violation_id
                    ),
                    entity_type="policy_violation",
                ),
                title=_TITLES[event.event_class],
                severity=severity,
                link=_link(event.violation_id, event.domain_id),
                correlation_id=event.correlation_id,
                dedup_key=f"violation:{event.violation_id}:{event.event_class}",
                dedup_window_seconds=DEDUP_WINDOW_SECONDS,
            )
        )

    async def _publish(self, event: NotificationEvent) -> None:
        try:
            await self._publisher.publish(event)
        except Exception as exc:
            _LOG.warning(
                "violation notification not queued",
                extra={"event": "govpolicy.notify_failed", "reason": type(exc).__name__},
            )
