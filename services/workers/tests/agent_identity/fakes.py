"""Fakes and builders for the worker agent identity source tests."""

from __future__ import annotations

from typing import Any

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.agent_identity import AgentIdentityResolver
from neurosphere_core.catalog.protocol import AliasKey
from neurosphere_workers.projections.catalog import LoadedEvent

CUSTOMER = "synthco"
TRACE = "c1f91e05fc394d5f81060f328b0307b7"


class StubLookup:
    """Canned values by alias value; counts calls; can raise."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.calls: list[AliasKey] = []
        self.error: Exception | None = None

    async def lookup(self, key: AliasKey) -> str | None:
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        return self.values.get(key.alias_value)


def make_resolver(lookup: StubLookup) -> AgentIdentityResolver:
    return AgentIdentityResolver(lookup, clock=lambda: 1000.0)


def doc(event_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": f"commercial:{CUSTOMER}:sandbox:domain:dom-001",
        "duration_ms": 10,
        "environment": "sandbox",
        "event_id": event_id,
        "event_time": "2026-10-01T01:07:21.470Z",
        "external_agent_id": "ext-1",
        "outcome": "success",
        "request_id": "req-1",
        "sampling": {"method": "none", "rate": 1.0},
        "schema_version": "1.0.0",
        "source_id": "sandbox-gateway",
        "span_id": "f6c75e5fa45fb230",
        "span_kind": "request",
        "trace_id": TRACE,
    }
    base.update(overrides)
    return base


def loaded(doc_id: str, payload: dict[str, Any]) -> LoadedEvent:
    return LoadedEvent(doc_id, TelemetryEvent.model_validate(payload))
