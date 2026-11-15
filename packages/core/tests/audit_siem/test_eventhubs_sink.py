"""PRP-40 item 1: the Event Hubs SIEM sink, sink health and the guarded exporter (fake producer)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import InMemoryAuditStore, find_sensitive_content
from neurosphere_core.audit.siem import SiemExporter
from neurosphere_core.audit.siem_eventhubs import EventHubsSiemSink, resolve_namespace
from neurosphere_core.audit.siem_health import (
    REASON_AUTH_FAILED,
    REASON_EVENT_BUILD_FAILED,
    REASON_SINK_ERROR,
    REASON_SINK_TIMEOUT,
    REASON_SINK_UNAVAILABLE,
    SiemSinkHealth,
    failure_reason,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.cloud.profile import profile_for

from .siem_helpers import CHAIN, drafts, make_repo

_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJl"
_EMAIL = "alice@contoso.com"
_GUID = "6f1d9a2e-3b4c-4d5e-8f60-718293a4b5c6"


class _Batch:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def add(self, event_data: Any) -> None:
        self.events.append(event_data)


class FakeProducer:
    """Records each sent batch; can fail N times with a chosen exception."""

    def __init__(self) -> None:
        self.sent: list[list[str]] = []
        self.fail_with: BaseException | None = None
        self.failures_left = 0
        self.delay = 0.0
        self.closed = False

    async def create_batch(self) -> _Batch:
        return _Batch()

    async def send_batch(self, event_data_batch: Any) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None and self.failures_left > 0:
            self.failures_left -= 1
            raise self.fail_with
        self.sent.append([e.body_as_str() for e in event_data_batch.events])

    async def close(self) -> None:
        self.closed = True


def _clock() -> datetime:
    return datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _record(**outcome: Any) -> AuditRecord:
    return AuditRecord.model_validate(
        {
            "schema_version": "1.0.0",
            "audit_id": "11111111-2222-4333-8444-555555555555",
            "chain_id": CHAIN,
            "sequence": 0,
            "previous_hash": None,
            "record_hash": "sha256:" + "0" * 64,
            "kind": "after",
            "recorded_at": "2026-10-10T17:05:20Z",
            "actor": {"principal_pseudonym": _GUID, "principal_kind": "user", "on_behalf_of": None},
            "scope_hash": "sha256:" + "1" * 64,
            "correlation_id": "corr-1",
            "operation": "action.execute",
            "channel": "rest",
            "intent_id": None,
            "subject": None,
            "outcome": {
                "result": "failed",
                "verified": False,
                "detail": f"{_EMAIL} Bearer {_JWT}",
                **outcome,
            },
            "denial": None,
        }
    )


async def test_each_append_emits_one_redacted_event_batch() -> None:
    producer = FakeProducer()
    health = SiemSinkHealth("eventhubs", clock=_clock)
    exporter = SiemExporter([EventHubsSiemSink(producer)], health=health)
    store = InMemoryAuditStore()
    repo = make_repo(store, exporter=exporter)
    for draft in drafts(3):
        await repo.append(CHAIN, draft)
    assert len(store.raw_documents(CHAIN)) == 3
    assert [len(batch) for batch in producer.sent] == [1, 1, 1]
    for (body,) in producer.sent:
        event = json.loads(body)
        assert event["event_type"] == "neurosphere.audit.v1"
        assert find_sensitive_content(event["record"]) == []
    snap = health.snapshot()
    assert snap.total_sent == 3 and snap.consecutive_failures == 0
    assert snap.last_success_at == _clock() and snap.last_failure_reason is None


async def test_unguarded_record_is_redacted_before_it_leaves() -> None:
    producer = FakeProducer()
    await SiemExporter([EventHubsSiemSink(producer)]).export(_record())
    (body,) = producer.sent[0]
    for secret in (_JWT, _EMAIL, _GUID):
        assert secret not in body


async def test_failures_are_counted_then_recover(caplog: pytest.LogCaptureFixture) -> None:
    producer = FakeProducer()
    producer.fail_with = ConnectionError(f"amqp down for {_EMAIL} at ns.servicebus.windows.net")
    producer.failures_left = 2
    health = SiemSinkHealth("eventhubs", clock=_clock)
    exporter = SiemExporter([EventHubsSiemSink(producer)], health=health)
    store = InMemoryAuditStore()
    repo = make_repo(store, exporter=exporter)
    with caplog.at_level(logging.WARNING):
        await repo.append(CHAIN, drafts(1)[0])
        await repo.append(CHAIN, drafts(2)[1])
    # The append never fails: both records are durable.
    assert len(store.raw_documents(CHAIN)) == 2
    snap = health.snapshot()
    assert snap.consecutive_failures == 2 and snap.total_failures == 2
    assert snap.last_failure_reason == REASON_SINK_UNAVAILABLE
    assert exporter.failures == 2
    # Never the exception text, host or a value in the log.
    assert _EMAIL not in caplog.text and "servicebus" not in caplog.text
    await exporter.export(_record())
    snap = health.snapshot()
    assert snap.consecutive_failures == 0 and snap.total_sent == 1
    assert snap.last_failure_reason == REASON_SINK_UNAVAILABLE  # last reason is kept


async def test_slow_send_times_out_as_a_counted_failure() -> None:
    producer = FakeProducer()
    producer.delay = 0.5
    health = SiemSinkHealth("eventhubs")
    exporter = SiemExporter([EventHubsSiemSink(producer, send_timeout_seconds=0.01)], health=health)
    await exporter.export(_record())
    assert health.snapshot().last_failure_reason == REASON_SINK_TIMEOUT
    assert producer.sent == []


async def test_event_build_failure_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    from neurosphere_core.audit import siem

    def boom(_record: AuditRecord) -> dict[str, Any]:
        raise ValueError("cannot serialise")

    monkeypatch.setattr(siem, "to_siem_event", boom)
    health = SiemSinkHealth("eventhubs")
    producer = FakeProducer()
    exporter = SiemExporter([EventHubsSiemSink(producer)], health=health)
    await exporter.export(_record())  # does not raise
    assert health.snapshot().last_failure_reason == REASON_EVENT_BUILD_FAILED
    assert producer.sent == []


async def test_signal_events_are_redacted() -> None:
    producer = FakeProducer()
    exporter = SiemExporter([EventHubsSiemSink(producer)])
    await exporter.export_signal(
        "neurosphere.authn.v1", {"reason": "invalid_token", "detail": f"{_EMAIL} {_JWT}"}
    )
    (body,) = producer.sent[0]
    event = json.loads(body)
    assert event["event_type"] == "neurosphere.authn.v1"
    assert event["signal"]["reason"] == "invalid_token"
    assert _EMAIL not in body and _JWT not in body


async def test_close_closes_the_producer() -> None:
    producer = FakeProducer()
    await EventHubsSiemSink(producer).close()
    assert producer.closed


def test_send_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        EventHubsSiemSink(FakeProducer(), send_timeout_seconds=0)


# -- reason codes ------------------------------------------------------------------------------


class ClientAuthenticationError(Exception):
    """Same class name as azure.core's; the mapping reads names, never messages."""


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (TimeoutError(), REASON_SINK_TIMEOUT),
        (ClientAuthenticationError("token for alice@contoso.com"), REASON_AUTH_FAILED),
        (ConnectionRefusedError(), REASON_SINK_UNAVAILABLE),
        (RuntimeError("x"), REASON_SINK_ERROR),
    ],
)
def test_failure_reason_is_a_code(exc: BaseException, reason: str) -> None:
    assert failure_reason(exc) == reason


# -- cloud hosts -------------------------------------------------------------------------------


def test_government_profile_uses_the_government_suffix() -> None:
    gov = profile_for(CloudName.GOVERNMENT)
    name = resolve_namespace(gov, "ns-audit")
    assert name == "ns-audit"
    assert gov.eventhubs_fqdn(name) == "ns-audit.servicebus.usgovcloudapi.net"
    assert resolve_namespace(gov, "ns-audit.servicebus.usgovcloudapi.net") == "ns-audit"


@pytest.mark.parametrize(
    "value",
    [
        "ns-audit.servicebus.windows.net",
        "sb://ns-audit.servicebus.windows.net/",
        "ns-audit.servicebus.usgovcloudapi.net.evil.example",
        "ns-audit.evilservicebus.usgovcloudapi.net",
    ],
)
def test_commercial_or_foreign_host_on_government_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        resolve_namespace(profile_for(CloudName.GOVERNMENT), value)


def test_government_host_on_commercial_is_refused() -> None:
    with pytest.raises(ValueError):
        resolve_namespace(
            profile_for(CloudName.COMMERCIAL), "ns-audit.servicebus.usgovcloudapi.net"
        )


@pytest.mark.parametrize("value", ["", "a", "Ns_Audit!", "x" * 60])
def test_invalid_namespace_names_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        resolve_namespace(profile_for(CloudName.COMMERCIAL), value)
