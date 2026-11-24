"""PRP-100 item 4: tool and service subject points, and no change to the model_call aggregates."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.aggregates import Contribution, SubjectPoint, subject_series_key

from neurosphere_workers.aggregates import rollups
from neurosphere_workers.aggregates.mapping import contribution_from_event
from neurosphere_workers.projections.catalog import LoadedEvent

from .support import CUST, DOMAIN, NOW, Rig, event_doc, wide_window

TOOL = f"commercial:{CUST}:src-1:tool:search"
SERVICE = f"commercial:{CUST}:src-1:service:db"
AGENT = f"commercial:{CUST}:src-1:agent:alpha"


def _at(minutes: int = 0):  # type: ignore[no-untyped-def]
    return NOW.replace(minute=0) - timedelta(hours=1) + timedelta(minutes=minutes)


def span(
    n: str,
    *,
    kind: str,
    minute: int = 0,
    duration_ms: int | None = 100,
    outcome: str | None = "success",
    tool: dict[str, Any] | None = None,
    service: dict[str, Any] | None = None,
    agent: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    tokens: tuple[int, int] | None = None,
) -> LoadedEvent:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": n,
        "event_time": _at(minute).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cloud": "commercial",
        "customer_id": CUST,
        "source_id": "src-1",
        "domain_id": DOMAIN,
        "span_kind": kind,
        "outcome": outcome,
    }
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if tool is not None:
        body["tool"] = tool
    if service is not None:
        body["service"] = service
    if agent:
        body["canonical_agent_id"] = agent
    if provider:
        body["provider"] = provider
    if model:
        body["model"] = model
    if tokens:
        body["token_breakdown"] = {"input": tokens[0], "output": tokens[1]}
    return LoadedEvent(doc_id=f"ev-{n}", event=TelemetryEvent.model_validate(body))


async def points(rig: Rig, metric: str = "subject") -> dict[str, Any]:
    result = await rig.aggregates.query(
        CUST,
        DOMAIN,
        metric,
        "hour",
        wide_window(rig, 13),
        max_series=50,
        max_points=100,
    )
    return {s.key: s.points[-1] for s in result.series}


def _contribution(loaded: LoadedEvent) -> Contribution | None:
    return contribution_from_event(CUST, loaded.doc_id, loaded.event)


async def test_tool_point_counts_errors_and_percentiles() -> None:
    rig = Rig()
    for i in range(10):
        await rig.add_event(
            span(
                f"t{i}",
                kind="tool_call",
                minute=i,
                duration_ms=(i + 1) * 10,
                outcome="error" if i < 3 else "success",
                tool={"tool_name": "search"},
            )
        )
    assert (await rig.drain()).ok
    point: SubjectPoint = (await points(rig))[subject_series_key("tool", TOOL)]
    assert point.subject_kind == "tool"
    assert point.event_count == 10
    assert point.error_count == 3
    assert point.error_rate == pytest.approx(0.3)
    assert point.p50_ms is not None and 50 <= point.p50_ms <= 60
    assert point.p95_ms is not None and 90 <= point.p95_ms <= 100
    assert point.input_tokens is None and point.output_tokens is None


async def test_unknown_outcomes_are_not_zero_errors() -> None:
    rig = Rig()
    for i in range(3):
        await rig.add_event(
            span(
                f"t{i}",
                kind="tool_call",
                minute=i,
                duration_ms=None,
                outcome=None,
                tool={"tool_name": "search"},
            )
        )
    assert (await rig.drain()).ok
    point = (await points(rig))[subject_series_key("tool", TOOL)]
    assert point.error_rate is None and point.error_count is None
    assert point.unknown_outcome_count == 3
    assert point.missing_duration_count == 3
    assert point.p50_ms is None and point.p95_ms is None


async def test_service_point_from_tool_model_and_agent_spans_but_not_unknown() -> None:
    rig = Rig()
    svc = {"external_service_id": "db"}
    await rig.add_event(span("a", kind="tool_call", tool={"tool_name": "search"}, service=svc))
    await rig.add_event(
        span("b", kind="model_call", minute=1, provider="p", model="m", service=svc)
    )
    await rig.add_event(span("c", kind="agent_run", minute=2, agent=AGENT, service=svc))
    await rig.add_event(span("d", kind="unknown", minute=3, service=svc))
    assert (await rig.drain()).ok
    got = await points(rig)
    service = got[subject_series_key("service", SERVICE)]
    assert service.subject_kind == "service"
    assert service.event_count == 3
    assert service.input_tokens is None
    # The agent_run span adds no agent point (agent points stay model_call only).
    assert subject_series_key("agent", AGENT) not in got


async def test_tool_span_without_usable_identity_adds_nothing() -> None:
    assert _contribution(span("a", kind="tool_call")) is None
    # A tool span with an id the resolver rejects (URL-like) and no service.
    assert _contribution(span("b", kind="tool_call", tool={"tool_name": "http://x/?k=v"})) is None
    # ... and it adds nothing for its agent either.
    assert _contribution(span("c", kind="tool_call", agent=AGENT)) is None
    # An agent_run without a service identity is still ignored.
    assert _contribution(span("d", kind="agent_run", agent=AGENT)) is None


async def test_foreign_customer_producer_id_is_replaced_by_the_derived_id() -> None:
    loaded = span(
        "a",
        kind="tool_call",
        tool={"canonical_tool_id": "commercial:cust-2:src-1:tool:evil", "tool_name": "search"},
    )
    contribution = _contribution(loaded)
    assert contribution is not None and contribution.event is not None
    assert contribution.event.tool_id == TOOL


async def test_old_stored_contribution_deserialises_as_model_call() -> None:
    contribution = _contribution(event_doc("x", at=_at(), duration_ms=5))
    assert contribution is not None and contribution.event is not None
    stored = contribution.model_dump(mode="json")
    for key in ("span_kind", "tool_id", "service_id"):
        del stored["event"][key]
    revived = Contribution.model_validate(stored)
    assert revived.event is not None and revived.event.span_kind == "model_call"
    assert revived == contribution


def _model_batch() -> list[LoadedEvent]:
    return [
        span(
            f"m{i}",
            kind="model_call",
            minute=i,
            duration_ms=None if i == 2 else 50 * (i + 1),
            outcome=("error", "success", "unknown")[i % 3],
            agent=AGENT if i % 2 == 0 else None,
            provider="p",
            model="m",
            tokens=(10, 5) if i != 1 else None,
        )
        for i in range(5)
    ]


def _extras() -> list[LoadedEvent]:
    tool = {"tool_name": "search"}
    svc = {"external_service_id": "db"}
    return [
        span("x1", kind="tool_call", minute=10, outcome="error", tool=tool, service=svc),
        span("x2", kind="tool_call", minute=11, duration_ms=None, tool=tool),
        span("x3", kind="agent_run", minute=12, agent=AGENT, service=svc),
        span("x4", kind="retrieval", minute=13, outcome="error", service=svc),
    ]


async def _run(events: list[LoadedEvent]) -> Rig:
    rig = Rig()
    for e in events:
        await rig.add_event(e)
    assert (await rig.drain()).ok
    return rig


async def test_mixed_batch_leaves_every_existing_metric_identical() -> None:
    base = await _run(_model_batch())
    mixed = await _run(_model_batch() + _extras())
    base_docs = base.snapshot()["docs"]
    mixed_docs = mixed.snapshot()["docs"]
    new = {
        k
        for k, v in mixed_docs.items()
        if v.get("metric") == "subject" and v.get("subject_kind") in ("tool", "service")
    }
    assert len(new) == 4  # tool + service at hour and day grain
    assert {k: v for k, v in mixed_docs.items() if k not in new} == base_docs


async def test_rerun_is_idempotent() -> None:
    rig = await _run(_model_batch() + _extras())
    once = rig.snapshot()
    again = await rig.replay_all()
    assert again.ok
    assert rig.snapshot() == once


async def test_cap_is_shared_across_all_kinds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(rollups, "MAX_SUBJECT_SERIES_PER_BUCKET", 2)
    rig = Rig()
    await rig.add_event(
        span(
            "a",
            kind="model_call",
            agent=AGENT,
            provider="p",
            model="m",
            service={"external_service_id": "db"},
        )
    )
    await rig.add_event(span("b", kind="tool_call", minute=1, tool={"tool_name": "search"}))
    with caplog.at_level(logging.WARNING):
        assert (await rig.drain()).ok
    got = await points(rig)
    assert len(got) == 2
    assert any(getattr(r, "dropped", None) == 2 for r in caplog.records)
