"""Violation event sink (PRP-105 item 3, clarification 12).

The evaluator tells a :class:`ViolationEventSink` when a violation opens, when one resolves and
when an exception decision reaches the engine. Events carry ids, the PRP-99
``NotificationEventClass`` value and the domain, never content. This PRP ships only
:class:`NoopViolationEventSink`; PRP-107 item 6 binds its notification publisher through the
worker assembly's ``violation_event_sink`` function (the one binding owner).

A sink must not fail the run: the evaluator logs a raising sink by reason and carries on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

__all__ = [
    "EXCEPTION_DECIDED",
    "VIOLATION_OPENED",
    "VIOLATION_RESOLVED",
    "ExceptionDecidedEvent",
    "NoopViolationEventSink",
    "ViolationEvent",
    "ViolationEventClass",
    "ViolationEventSink",
]

ViolationEventClass = Literal[
    "policy_violation_opened", "policy_violation_resolved", "policy_exception_decided"
]

#: PRP-99 ``NotificationEventClass`` values this sink emits (a test pins them to the contract).
VIOLATION_OPENED: Final = "policy_violation_opened"
VIOLATION_RESOLVED: Final = "policy_violation_resolved"
EXCEPTION_DECIDED: Final = "policy_exception_decided"


@dataclass(frozen=True, slots=True)
class ViolationEvent:
    """A violation opened or resolved: ids only."""

    event_class: ViolationEventClass
    cloud: str
    customer_id: str
    domain_id: str
    violation_id: str
    policy_id: str
    policy_version: int
    rule_id: str
    subject_id: str
    severity: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ExceptionDecidedEvent:
    """An exception decision the engine applied (``approved``, ``rejected`` or ``expired``)."""

    cloud: str
    customer_id: str
    domain_id: str
    exception_id: str
    violation_id: str | None
    policy_id: str
    rule_id: str
    subject_id: str
    status: Literal["approved", "rejected", "expired", "revoked"]
    correlation_id: str
    event_class: ViolationEventClass = EXCEPTION_DECIDED


@runtime_checkable
class ViolationEventSink(Protocol):
    """Where violation events go. Implementations must not block the run for long."""

    async def opened(self, event: ViolationEvent) -> None: ...

    async def resolved(self, event: ViolationEvent) -> None: ...

    async def exception_decided(self, event: ExceptionDecidedEvent) -> None: ...


class NoopViolationEventSink:
    """The default sink: drops every event (PRP-107 binds the real one)."""

    async def opened(self, event: ViolationEvent) -> None:
        return None

    async def resolved(self, event: ViolationEvent) -> None:
        return None

    async def exception_decided(self, event: ExceptionDecidedEvent) -> None:
        return None
