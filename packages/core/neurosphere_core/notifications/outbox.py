"""Durable outbox: store protocol, in-memory twin, state machine, claim, backoff, dedup.

State machine over the contract statuses (anything else is ``invalid_transition``)::

    pending  -> sending                      (claim: ETag compare-and-swap, attempts + 1)
    sending  -> delivered                    (a 2xx)
    sending  -> pending                      (retryable failure with attempts left, backoff)
    sending  -> failed                       (permanent failure, or attempt cap reached)
    sending  -> sending                      (reclaim after the lease expired: a dead worker)
    pending | sending | failed -> suppressed (scope lost, channel or subscription gone)
    failed   -> dead_lettered                (operator or worker gives up for good)

``delivered``, ``suppressed`` and ``dead_lettered`` are final. ``attempts`` counts claims.

De-duplication: ``dedup_key`` is ``sha256:`` + the digest of (customer, event class, subscription,
caller key). ``notification_id`` is a UUIDv5 over the dedup key and the window bucket, so a
create-if-absent conflict collapses concurrent or restarted publishes of one logical event, and a
``find_by_dedup`` lookup over the window closes the gap at a bucket boundary. Both stores behave
identically (one contract test suite runs against both).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.errors import StaleVersionError
from neurosphere_core.notifications.message import safe_title
from neurosphere_core.notifications.models import (
    NOTIFICATION_SCHEMA_VERSION,
    DeliveryStatus,
    NotificationDelivery,
    NotificationEvent,
    RetryPolicy,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FINAL_STATUSES",
    "InMemoryOutboxStore",
    "Outbox",
    "OutboxEntry",
    "OutboxStore",
    "compute_dedup_key",
    "format_timestamp",
    "invalid_transition",
    "notification_id_for",
    "parse_timestamp",
]

_NAMESPACE: Final = uuid.UUID("5d0e3b6e-62d1-4b0b-9a53-1f0c1e8a7c07")
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"sending", "suppressed"}),
    "sending": frozenset({"sending", "delivered", "pending", "failed", "suppressed"}),
    "failed": frozenset({"dead_lettered", "suppressed"}),
    "delivered": frozenset(),
    "suppressed": frozenset(),
    "dead_lettered": frozenset(),
}
FINAL_STATUSES: Final = frozenset({"delivered", "suppressed", "dead_lettered"})
DEFAULT_LEASE_SECONDS: Final = 300
Clock = Callable[[], datetime]


def format_timestamp(moment: datetime) -> str:
    """Contract ``Timestamp`` (UTC, ``Z``), whole seconds so string order is time order."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def invalid_transition(old: str, new: str) -> StaleVersionError:
    return StaleVersionError(
        f"outbox row cannot move from {old} to {new}", reason="invalid_transition"
    )


def compute_dedup_key(
    customer_id: str, event_class: str, subscription_id: str, caller_key: str
) -> str:
    material = "\x1f".join((customer_id, event_class, subscription_id, caller_key))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def notification_id_for(dedup_key: str, now: datetime, window_seconds: int) -> str:
    """Deterministic id per dedup key and window bucket; a zero window gets a random id."""
    if window_seconds <= 0:
        return str(uuid.uuid4())
    bucket = int(now.timestamp()) // window_seconds
    return str(uuid.uuid5(_NAMESPACE, f"{dedup_key}|{bucket}"))


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """A stored row with the store's ETag (the compare-and-swap token)."""

    delivery: NotificationDelivery
    etag: str


@runtime_checkable
class OutboxStore(Protocol):
    async def create_if_absent(self, delivery: NotificationDelivery) -> tuple[OutboxEntry, bool]:
        """``(entry, True)`` when created, ``(existing, False)`` when the id already exists."""
        ...

    async def get(self, customer_id: str, notification_id: str) -> OutboxEntry | None: ...

    async def find_by_dedup(
        self, customer_id: str, dedup_key: str, *, since: datetime
    ) -> OutboxEntry | None:
        """A row with this dedup key created at or after ``since``, if any."""
        ...

    async def due(
        self, *, now: datetime, limit: int, customer_id: str | None = None
    ) -> list[OutboxEntry]:
        """Rows ``pending`` or ``sending`` whose ``next_attempt_at`` is at or before ``now``."""
        ...

    async def list_deliveries(
        self,
        customer_id: str,
        *,
        status: str | None = None,
        channel_id: str | None = None,
        limit: int = 100,
        newest_first: bool = False,
    ) -> list[OutboxEntry]: ...

    async def count_deliveries(self, customer_id: str, *, channel_id: str, status: str) -> int:
        """Rows of one channel in one status (a single-partition count, no rows read)."""
        ...

    async def last_error_code(self, customer_id: str, channel_id: str) -> str | None:
        """Reason code of the latest ``failed`` (else ``dead_lettered``) row of the channel."""
        ...

    async def replace(self, entry: OutboxEntry, delivery: NotificationDelivery) -> OutboxEntry:
        """ETag compare-and-swap; a changed or missing row is ``stale_version`` (etag_mismatch)."""
        ...


class InMemoryOutboxStore:
    """Twin of :class:`~neurosphere_core.notifications.cosmos_store.CosmosOutboxStore`."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], OutboxEntry] = {}
        self._counter = 0
        self.error: BaseException | None = None

    def fail_with(self, error: BaseException | None) -> None:
        self.error = error

    def _guard(self) -> None:
        if self.error is not None:
            raise self.error

    def _stamp(self, delivery: NotificationDelivery) -> OutboxEntry:
        self._counter += 1
        entry = OutboxEntry(delivery, f'"{self._counter}"')
        self._rows[(delivery.customer_id.root, delivery.notification_id.root)] = entry
        return entry

    async def create_if_absent(self, delivery: NotificationDelivery) -> tuple[OutboxEntry, bool]:
        self._guard()
        existing = self._rows.get((delivery.customer_id.root, delivery.notification_id.root))
        if existing is not None:
            return existing, False
        return self._stamp(delivery), True

    async def get(self, customer_id: str, notification_id: str) -> OutboxEntry | None:
        self._guard()
        return self._rows.get((customer_id, notification_id))

    async def find_by_dedup(
        self, customer_id: str, dedup_key: str, *, since: datetime
    ) -> OutboxEntry | None:
        self._guard()
        wanted = format_timestamp(since)
        for (customer, _), entry in sorted(self._rows.items()):
            d = entry.delivery
            if customer == customer_id and d.dedup_key == dedup_key and d.created_at.root >= wanted:
                return entry
        return None

    async def due(
        self, *, now: datetime, limit: int, customer_id: str | None = None
    ) -> list[OutboxEntry]:
        self._guard()
        cutoff = format_timestamp(now)
        rows = [
            e
            for (customer, _), e in self._rows.items()
            if (customer_id is None or customer == customer_id)
            and e.delivery.status in ("pending", "sending")
            and e.delivery.next_attempt_at is not None
            and e.delivery.next_attempt_at.root <= cutoff
        ]
        rows.sort(key=lambda e: (e.delivery.next_attempt_at.root, e.delivery.notification_id.root))  # type: ignore[union-attr]
        return rows[:limit]

    async def list_deliveries(
        self,
        customer_id: str,
        *,
        status: str | None = None,
        channel_id: str | None = None,
        limit: int = 100,
        newest_first: bool = False,
    ) -> list[OutboxEntry]:
        self._guard()
        rows = [
            e
            for (customer, _), e in self._rows.items()
            if customer == customer_id
            and (status is None or e.delivery.status == status)
            and (channel_id is None or e.delivery.channel_id.root == channel_id)
        ]
        rows.sort(
            key=lambda e: (e.delivery.created_at.root, e.delivery.notification_id.root),
            reverse=newest_first,
        )
        return rows[:limit]

    async def count_deliveries(self, customer_id: str, *, channel_id: str, status: str) -> int:
        self._guard()
        return sum(
            1
            for (customer, _), e in self._rows.items()
            if customer == customer_id
            and e.delivery.channel_id.root == channel_id
            and e.delivery.status == status
        )

    async def last_error_code(self, customer_id: str, channel_id: str) -> str | None:
        self._guard()
        for status in ("failed", "dead_lettered"):
            rows = [
                e.delivery
                for (customer, _), e in self._rows.items()
                if customer == customer_id
                and e.delivery.channel_id.root == channel_id
                and e.delivery.status == status
                and e.delivery.last_error_code is not None
            ]
            if rows:
                rows.sort(key=lambda d: (d.created_at.root, d.notification_id.root))
                code = rows[-1].last_error_code
                return code.root if code is not None else None
        return None

    async def replace(self, entry: OutboxEntry, delivery: NotificationDelivery) -> OutboxEntry:
        self._guard()
        key = (delivery.customer_id.root, delivery.notification_id.root)
        current = self._rows.get(key)
        if current is None or current.etag != entry.etag:
            raise StaleVersionError("outbox row changed since it was read", reason="etag_mismatch")
        return self._stamp(delivery)


class Outbox:
    """State-machine service over any :class:`OutboxStore`.

    Every mutator returns the new entry, or ``None`` when another worker changed the row first
    (the compare-and-swap lost); the caller then leaves the row alone. A transition the table
    forbids raises ``stale_version`` (``invalid_transition``).
    """

    def __init__(
        self,
        store: OutboxStore,
        *,
        clock: Clock = _utc_now,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._store = store
        self._clock = clock
        self._lease = lease_seconds

    @property
    def store(self) -> OutboxStore:
        return self._store

    # -- enqueue ----------------------------------------------------------------------------

    async def enqueue(
        self,
        event: NotificationEvent,
        *,
        subscription_id: str,
        channel_id: str,
        window_seconds: int,
    ) -> tuple[OutboxEntry, bool]:
        """Create the ``pending`` row for one (event, subscription) unless it is a duplicate."""
        now = self._clock()
        dedup_key = compute_dedup_key(
            event.customer_id, event.event_class, subscription_id, event.dedup_key
        )
        if window_seconds > 0:
            seen = await self._store.find_by_dedup(
                event.customer_id, dedup_key, since=now - timedelta(seconds=window_seconds)
            )
            if seen is not None:
                return seen, False
        stamp = format_timestamp(now)
        delivery = NotificationDelivery.model_validate(
            {
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "notification_id": notification_id_for(dedup_key, now, window_seconds),
                "cloud": event.cloud,
                "customer_id": event.customer_id,
                "domain_id": event.domain_id,
                "channel_id": channel_id,
                "subscription_id": subscription_id,
                "event_class": event.event_class,
                "severity": event.severity,
                "subject": event.subject.model_dump(mode="json"),
                "title": safe_title(event.title),
                "link": event.link,
                "correlation_id": event.correlation_id,
                "dedup_key": dedup_key,
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": stamp,
                "created_at": stamp,
                "source_audit_id": event.source_audit_id,
            }
        )
        return await self._store.create_if_absent(delivery)

    # -- transitions ------------------------------------------------------------------------

    async def claim(self, entry: OutboxEntry) -> OutboxEntry | None:
        """``pending`` (due) or lease-expired ``sending`` to ``sending``; ``None`` if lost."""
        now = self._clock()
        d = entry.delivery
        due = d.next_attempt_at is not None and d.next_attempt_at.root <= format_timestamp(now)
        if d.status not in ("pending", "sending") or not due:
            return None
        return await self._swap(
            entry,
            status="sending",
            attempts=d.attempts + 1,
            next_attempt_at=format_timestamp(now + timedelta(seconds=self._lease)),
        )

    async def mark_delivered(
        self, entry: OutboxEntry, *, status_code: int | None = None
    ) -> OutboxEntry | None:
        return await self._swap(
            entry,
            status="delivered",
            next_attempt_at=None,
            last_error_code=f"http_{status_code}" if status_code is not None else None,
            delivered_at=format_timestamp(self._clock()),
        )

    async def mark_attempt_failed(
        self, entry: OutboxEntry, *, reason: str, retryable: bool, policy: RetryPolicy
    ) -> OutboxEntry | None:
        """Retry with backoff while attempts remain and the failure is retryable, else failed."""
        d = entry.delivery
        if retryable and d.attempts < policy.max_attempts:
            delay = timedelta(seconds=policy.backoff_seconds(d.attempts))
            return await self._swap(
                entry,
                status="pending",
                next_attempt_at=format_timestamp(self._clock() + delay),
                last_error_code=reason,
            )
        return await self._swap(
            entry, status="failed", next_attempt_at=None, last_error_code=reason
        )

    async def suppress(self, entry: OutboxEntry, *, reason: str = "scope") -> OutboxEntry | None:
        return await self._swap(
            entry, status="suppressed", next_attempt_at=None, last_error_code=reason
        )

    async def dead_letter(self, entry: OutboxEntry) -> OutboxEntry | None:
        return await self._swap(entry, status="dead_lettered", next_attempt_at=None)

    async def _swap(
        self, entry: OutboxEntry, *, status: DeliveryStatus, **changes: object
    ) -> OutboxEntry | None:
        old = entry.delivery.status
        if status not in ALLOWED_TRANSITIONS.get(old, frozenset()):
            raise invalid_transition(old, status)
        fields = entry.delivery.model_dump(mode="json")
        fields.update(changes)
        fields["status"] = status
        updated = NotificationDelivery.model_validate(
            {k: v for k, v in fields.items() if v is not None}
        )
        try:
            return await self._store.replace(entry, updated)
        except StaleVersionError as exc:
            if exc.reason == "etag_mismatch":
                return None
            raise
