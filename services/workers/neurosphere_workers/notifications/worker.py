"""Durable notification delivery worker (PRP-107 item 5).

Each tick: ``store.due`` -> per row ``claim`` (ETag compare-and-swap; a lost race skips the row) ->
scope recheck -> closed-field message -> sender -> ``delivered`` / retry with backoff / ``failed``.

The worker keeps no delivery state: attempts, backoff and the lease live on the outbox row, so a
restarted or second worker computes the same work from the store. A worker that dies after
``claim`` leaves the row ``sending`` with ``next_attempt_at`` = claim time + lease; once the lease
expires the row is due again and the next claim takes it over (never earlier, so two live workers
never both send).

Outcomes per row:

* scope lost -> ``suppressed`` (``scope``); no HTTP request is made;
* scope recheck cannot be answered -> back to ``pending`` with backoff
  (``scope_recheck_unavailable``), never sent and never silently dropped;
* sender ``ok`` -> ``delivered``;
* sender failure -> backoff while attempts remain and the failure is retryable, else ``failed``.

A row that reaches ``failed`` raises one counter and writes exactly one ``notification.delivery``
audit record naming the channel id, the notification id and the reason code. Neither the counter,
the audit record nor any log line carries the URL, the query, the headers, the secret or the title.

No ``NotificationsSetting`` document for the customer: the tick is skipped (counted), rows stay
``pending``. Without the setting there is no egress allow-list, so nothing may leave.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    make_subject,
    sha256_digest,
)
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.notifications.egress import EgressGuard
from neurosphere_core.notifications.message import build_message
from neurosphere_core.notifications.models import (
    NotificationChannel,
    NotificationDelivery,
    NotificationsSetting,
    RetryPolicy,
)
from neurosphere_core.notifications.outbox import Outbox, OutboxEntry
from neurosphere_core.notifications.ports import Sender
from neurosphere_core.notifications.registry import ChannelRegistry
from neurosphere_core.notifications.resolver import SubscriptionResolver
from neurosphere_core.notifications.senders import KindNotBuildableError, build_sender
from neurosphere_core.notifications.senders.base import SecretReader
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Meter

__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "METER_NAME",
    "OPERATION",
    "ROLE_NAME",
    "NotificationDeliveryWorker",
    "TickReport",
]

logger = logging.getLogger("neurosphere.workers.notifications")

ROLE_NAME: Final = "notifications"
METER_NAME: Final = "neurosphere_workers.notifications"
OPERATION: Final = "notification.delivery"
DEFAULT_BATCH_LIMIT: Final = 50

SKIP_NO_SETTING: Final = "notifications_setting_missing"
REASON_SCOPE_UNAVAILABLE: Final = "scope_recheck_unavailable"
REASON_SENDER_ERROR: Final = "sender_error"
REASON_SEND_FAILED: Final = "send_failed"

_REASON: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ACTOR: Final = Actor(
    principal_pseudonym="svc.neurosphere-notifications",
    principal_kind="service_principal",
    on_behalf_of=None,
)
_SCOPE_HASH: Final = sha256_digest({"system_scope": "neurosphere.notifications"})

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_reason(reason: str | None) -> str:
    return reason if reason is not None and _REASON.fullmatch(reason) else REASON_SEND_FAILED


@dataclass(frozen=True, slots=True)
class TickReport:
    at: datetime
    due: int = 0
    delivered: int = 0
    suppressed: int = 0
    retried: int = 0
    failed: int = 0
    conflicts: int = 0
    skipped: str | None = None


class NotificationDeliveryWorker:
    """One tick of outbox delivery over any :class:`OutboxStore`."""

    partition_key = ROLE_NAME

    def __init__(
        self,
        *,
        outbox: Outbox,
        registry: ChannelRegistry,
        resolver: SubscriptionResolver,
        secrets: SecretReader,
        guard: EgressGuard,
        audit: AuditRepository,
        customer_id: str,
        ns_env: str,
        deployment_cloud: str,
        clock: Clock = _utc_now,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        meter: Meter | None = None,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("batch_limit must be >= 1")
        self._outbox = outbox
        self._registry = registry
        self._resolver = resolver
        self._secrets = secrets
        self._guard = guard
        self._audit = audit
        self._customer = customer_id
        self._ns_env = ns_env
        self._cloud = deployment_cloud
        self._clock = clock
        self._limit = batch_limit
        meter = meter or otel_metrics.get_meter(METER_NAME)
        self._delivered: Any = meter.create_counter("ns.notifications.delivered", unit="{message}")
        self._suppressed: Any = meter.create_counter(
            "ns.notifications.suppressed", unit="{message}"
        )
        self._failed: Any = meter.create_counter("ns.notifications.failed", unit="{message}")
        self._skipped: Any = meter.create_counter("ns.notifications.tick_skipped", unit="{tick}")
        self._audit_failed: Any = meter.create_counter(
            "ns.notifications.audit_failed", unit="{record}"
        )
        self.last_report: TickReport | None = None

    # -- tick -------------------------------------------------------------------------------

    async def tick(self) -> TickReport:
        now = self._clock()
        setting = await self._registry.settings(self._customer)
        if setting is None:
            self._skipped.add(1, {"reason": SKIP_NO_SETTING})
            logger.info("notification tick skipped", extra={"reason": SKIP_NO_SETTING})
            self.last_report = TickReport(at=now, skipped=SKIP_NO_SETTING)
            return self.last_report
        policy = RetryPolicy.from_setting(setting)
        due = await self._outbox.store.due(now=now, limit=self._limit, customer_id=self._customer)
        senders: dict[str, Sender] = {}
        counts = {"delivered": 0, "suppressed": 0, "retried": 0, "failed": 0, "conflicts": 0}
        for entry in due:
            outcome = await self._deliver(entry, setting, policy, senders)
            counts[outcome] += 1
        self.last_report = TickReport(
            at=now,
            due=len(due),
            delivered=counts["delivered"],
            suppressed=counts["suppressed"],
            retried=counts["retried"],
            failed=counts["failed"],
            conflicts=counts["conflicts"],
        )
        return self.last_report

    # -- one row ----------------------------------------------------------------------------

    async def _deliver(
        self,
        entry: OutboxEntry,
        setting: NotificationsSetting,
        policy: RetryPolicy,
        senders: dict[str, Sender],
    ) -> str:
        claimed = await self._outbox.claim(entry)
        if claimed is None:
            return "conflicts"
        row = claimed.delivery
        decision = await self._resolver.recheck_for_delivery(row)
        if decision.suppress:
            moved = await self._outbox.suppress(claimed, reason=_safe_reason(decision.reason))
            if moved is None:
                return "conflicts"
            self._suppressed.add(1, self._labels(row, None, _safe_reason(decision.reason)))
            return "suppressed"
        if not decision.allowed or decision.channel is None:
            return await self._fail(claimed, None, REASON_SCOPE_UNAVAILABLE, True, policy)
        channel = decision.channel
        try:
            sender = senders.get(channel.kind)
            if sender is None:
                sender = build_sender(
                    channel.kind,
                    self._guard,
                    self._secrets,
                    setting=setting,
                    deployment_cloud=self._cloud,
                    ns_env=self._ns_env,
                    clock=self._clock,
                )
                senders[channel.kind] = sender
        except KindNotBuildableError as exc:
            return await self._fail(claimed, channel, _safe_reason(exc.reason), False, policy)
        try:
            sent = await sender.send(
                channel, build_message(row), notification_id=row.notification_id.root
            )
        except Exception:
            # The exception text may carry a URL; only the fact of the failure is kept.
            return await self._fail(claimed, channel, REASON_SENDER_ERROR, True, policy)
        if sent.delivered:
            moved = await self._outbox.mark_delivered(claimed, status_code=sent.status_code)
            if moved is None:
                return "conflicts"
            self._delivered.add(1, self._labels(row, channel, "delivered"))
            return "delivered"
        return await self._fail(
            claimed, channel, _safe_reason(sent.reason_code), sent.retryable, policy
        )

    async def _fail(
        self,
        claimed: OutboxEntry,
        channel: NotificationChannel | None,
        reason: str,
        retryable: bool,
        policy: RetryPolicy,
    ) -> str:
        row = claimed.delivery
        moved = await self._outbox.mark_attempt_failed(
            claimed, reason=reason, retryable=retryable, policy=policy
        )
        if moved is None:
            return "conflicts"
        if moved.delivery.status != "failed":
            logger.info(
                "notification attempt failed; retry scheduled",
                extra={"channel_id": row.channel_id.root, "reason": reason},
            )
            return "retried"
        self._failed.add(1, self._labels(row, channel, reason))
        logger.warning(
            "notification failed",
            extra={"channel_id": row.channel_id.root, "reason": reason},
        )
        await self._audit_failure(moved.delivery, reason)
        return "failed"

    async def _audit_failure(self, row: NotificationDelivery, reason: str) -> None:
        """Exactly one record per failed row; a failed audit write is counted and logged."""
        try:
            ctx = AuditContext.model_validate(
                {
                    "actor": _ACTOR.model_dump(mode="json"),
                    "scope_hash": _SCOPE_HASH,
                    "correlation_id": row.correlation_id,
                    "operation": OPERATION,
                    "channel": "worker",
                }
            )
            # The audit content guard refuses GUIDs in a canonical id or a detail, so the target
            # is the CHANNEL (a slug) and the notification id rides in ``target_version``.
            subject = make_subject(
                f"{row.cloud.root}:{row.customer_id.root}:notifications:notification_channel:"
                f"{row.channel_id.root}",
                "notification_channel",
                target_version=row.notification_id.root,
                state_digest=sha256_digest(
                    {
                        "notification_id": row.notification_id.root,
                        "channel_id": row.channel_id.root,
                        "status": "failed",
                    }
                ),
            )
            await self._audit.append(
                domain_audit_chain_id(row.customer_id.root, row.domain_id.root),
                build_after(
                    ctx,
                    subject,
                    result="failed",
                    verified=False,
                    detail=f"delivery_failed:{reason}",
                ),
            )
        except Exception as exc:
            self._audit_failed.add(1, {"event_class": row.event_class.root})
            # The exception class only: its text could carry store details.
            logger.error(
                "notification failure audit write failed",
                extra={
                    "channel_id": row.channel_id.root,
                    "reason": reason,
                    "error_type": type(exc).__name__,
                },
            )

    @staticmethod
    def _labels(
        row: NotificationDelivery, channel: NotificationChannel | None, reason: str
    ) -> dict[str, str]:
        return {
            "event_class": row.event_class.root,
            "channel_kind": channel.kind if channel is not None else "unknown",
            "reason": reason,
        }
