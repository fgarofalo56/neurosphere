"""Hand-built contract documents for the archive source tests."""

from __future__ import annotations

from typing import Any


def telemetry_doc(
    n: int,
    *,
    agent: str = "commercial:synthco:sandbox:agent:a-1",
    cloud: str = "commercial",
    customer: str = "synthco",
    domain: str = "commercial:synthco:sandbox:domain:dom-001",
    day: str = "2026-10-01",
    duration: int = 100,
) -> dict[str, Any]:
    return {
        "canonical_agent_id": agent,
        "cloud": cloud,
        "customer_id": customer,
        "domain_id": domain,
        "duration_ms": duration,
        "environment": "sandbox",
        "event_id": f"evt-{n:016x}-01",
        "event_time": f"{day}T01:00:00.000Z",
        "external_agent_id": "ext-a-1",
        "outcome": "success",
        "request_id": f"req-{n:012x}",
        "sampling": {"method": "none", "rate": 1.0},
        "schema_version": "1.0.0",
        "source_id": "sandbox-gateway",
        "span_id": f"{n:016x}",
        "span_kind": "request",
        "trace_id": f"{n:032x}",
    }
