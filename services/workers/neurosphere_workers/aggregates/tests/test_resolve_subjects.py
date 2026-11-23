"""Pure tool/service canonical id resolver (PRP-100 item 2)."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent

from neurosphere_workers.ingestion.resolve_subjects import (
    canonical_service_id,
    canonical_tool_id,
)

CUST = "cust-1"


def _event(
    tool: dict[str, Any] | None = None,
    service: dict[str, Any] | None = None,
    *,
    cloud: str = "commercial",
    source: str = "Src-1",
) -> TelemetryEvent:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": "e1",
        "event_time": "2026-11-14T12:00:00Z",
        "cloud": cloud,
        "customer_id": CUST,
        "source_id": source,
        "span_kind": "tool_call",
    }
    if tool is not None:
        body["tool"] = tool
    if service is not None:
        body["service"] = service
    return TelemetryEvent.model_validate(body)


def test_no_identity_gives_none() -> None:
    assert canonical_tool_id(_event(), CUST) is None
    assert canonical_service_id(_event(), CUST) is None


def test_owned_producer_value_is_used() -> None:
    own = f"commercial:{CUST}:other:tool:Weird/x".lower()
    assert (
        canonical_tool_id(_event({"canonical_tool_id": own, "external_tool_id": "z"}), CUST) == own
    )
    svc = f"commercial:{CUST}:other:service:db"
    assert canonical_service_id(_event(service={"canonical_service_id": svc}), CUST) == svc


@pytest.mark.parametrize(
    "bad",
    [
        "commercial:cust-2:s:tool:x",  # foreign customer
        "government:cust-1:s:tool:x",  # foreign cloud
        "commercial:cust-1:s:service:x",  # wrong type
        "commercial:cust-1:s:tool:x y",  # bad grammar
        "commercial:cust-1:s:tool:" + "a" * 600,  # too long
    ],
)
def test_unowned_producer_value_falls_back_to_derivation(bad: str) -> None:
    tool: dict[str, Any] = {"external_tool_id": "Search"}
    if len(bad) <= 512 and " " not in bad:
        tool["canonical_tool_id"] = bad
    got = canonical_tool_id(_event(tool), CUST)
    assert got == f"commercial:{CUST}:src-1:tool:search"


def test_derivation_from_external_id_name_fallback_and_lowercase() -> None:
    assert canonical_tool_id(_event({"external_tool_id": "Web.Search/v1"}), CUST) == (
        f"commercial:{CUST}:src-1:tool:web.search/v1"
    )
    assert canonical_tool_id(_event({"tool_name": "Calc"}), CUST) == (
        f"commercial:{CUST}:src-1:tool:calc"
    )
    assert canonical_service_id(_event(service={"external_service_id": "DB-1"}), CUST) == (
        f"commercial:{CUST}:src-1:service:db-1"
    )
    gov = _event({"external_tool_id": "x"}, cloud="government")
    assert canonical_tool_id(gov, CUST) == f"government:{CUST}:src-1:tool:x"


@pytest.mark.parametrize("bad", ["https://x/y?token=a", "has space", "a@b", "a:b", "a#b"])
def test_unsafe_external_ids_give_none(bad: str) -> None:
    assert canonical_tool_id(_event({"external_tool_id": bad}), CUST) is None
    assert canonical_service_id(_event(service={"external_service_id": bad}), CUST) is None


def test_missing_or_oversized_inputs_give_none() -> None:
    assert canonical_tool_id(_event({}), CUST) is None
    assert canonical_service_id(_event(service={}), CUST) is None
    long = "a" * 256  # the contract caps ids at 256, so push the total over 512 via the source
    long_event = _event({"external_tool_id": long}, source="s" * 128)
    assert canonical_tool_id(long_event, CUST * 30) is None  # customer long enough to overflow
    assert canonical_tool_id(_event({"external_tool_id": "x"}), "Bad Customer") is None
    assert canonical_tool_id(_event({"external_tool_id": "x"}), "") is None


def test_deterministic() -> None:
    event = _event({"external_tool_id": "Search"})
    assert canonical_tool_id(event, CUST) == canonical_tool_id(event, CUST)
