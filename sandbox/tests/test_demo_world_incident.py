"""Demo-world telemetry and the scripted incident (PRP-71 item 2): offline and deterministic."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent

from sandbox.demo.build import DemoWorld, build_demo_world
from sandbox.demo.incident import (
    HOUR_MS,
    DemoTelemetry,
    build_demo_telemetry,
    incident_manifest,
    write_demo_telemetry,
    write_incident_manifest,
)
from sandbox.ids import fmt_ts_s
from sandbox.tests.support import (
    COST_SCHEMA,
    TELEMETRY_SCHEMA,
    read_json,
    schema_valid,
    sha256_of,
)
from sandbox.world import DAY_MS

Doc = dict[str, Any]
SEED = 1
ERRORS = {"error", "timeout"}
DEGRADED = 0.05  # aggregates: health degraded at >= 0.05, failing at >= 0.25
FAILING = 0.25
NORMAL_MAX = 0.05  # unrelated agents must stay strictly below the degraded threshold


@pytest.fixture(scope="module")
def world() -> DemoWorld:
    return build_demo_world("commercial")


@pytest.fixture(scope="module")
def tele(world: DemoWorld) -> DemoTelemetry:
    return build_demo_telemetry(world, SEED)


def _window(manifest: Doc) -> tuple[str, str]:
    return manifest["window"]["start"], manifest["window"]["end"]


def _rates(events: list[Doc], start: str, end: str) -> dict[str, float]:
    total: dict[str, int] = defaultdict(int)
    errs: dict[str, int] = defaultdict(int)
    for e in events:
        if not (start <= e["event_time"] < end):
            continue
        total[e["canonical_agent_id"]] += 1
        errs[e["canonical_agent_id"]] += e["outcome"] in ERRORS
    return {a: errs[a] / n for a, n in total.items()}


def test_every_event_and_cost_validates(tele: DemoTelemetry) -> None:
    assert tele.events and tele.costs
    for ev in tele.events:
        TelemetryEvent.model_validate(ev)
        assert schema_valid(TELEMETRY_SCHEMA, ev), ev["event_id"]
    for c in tele.costs:
        CostRecord.model_validate(c)
        assert schema_valid(COST_SCHEMA, c), c["cost_id"]


def test_volume_is_modest(tele: DemoTelemetry) -> None:
    assert 1_000 < len(tele.events) < 12_000


def test_downstream_set_matches_manifest_and_world(world: DemoWorld, tele: DemoTelemetry) -> None:
    start, end = _window(tele.manifest)
    rates = _rates(tele.events, start, end)
    elevated = {a for a, r in rates.items() if r >= DEGRADED}
    assert elevated == set(tele.manifest["downstream_agent_ids"]) == set(world.downstream_agent_ids)
    assert len(world.downstream_agent_ids) == 5
    for agent_id in world.downstream_agent_ids:
        assert rates[agent_id] >= FAILING, agent_id
    for agent_id in world.unrelated_agent_ids + world.undeclared_agent_ids:
        assert rates[agent_id] < NORMAL_MAX, agent_id
    assert {t["subject_id"] for t in tele.manifest["expected_health_transitions"]} == set(
        world.downstream_agent_ids
    )


def test_baseline_hour_is_healthy_for_everyone(tele: DemoTelemetry) -> None:
    b = tele.manifest["baseline_window"]
    rates = _rates(tele.events, b["start"], b["end"])
    assert len(rates) == 36
    assert max(rates.values()) < NORMAL_MAX


def test_window_is_last_hour_of_seeded_window(world: DemoWorld, tele: DemoTelemetry) -> None:
    from sandbox.config import parse_epoch

    end_ms = parse_epoch(world.epoch) + world.days * DAY_MS
    assert tele.manifest["window"] == {"start": fmt_ts_s(end_ms - HOUR_MS), "end": fmt_ts_s(end_ms)}
    assert tele.manifest["service_id"] == world.outage_service_id
    assert max(e["event_time"] for e in tele.events) < fmt_ts_s(end_ms)
    start, end = _window(tele.manifest)
    in_window = [e for e in tele.events if start <= e["event_time"] < end]
    assert in_window


def test_latency_is_raised_on_failing_service_spans(world: DemoWorld, tele: DemoTelemetry) -> None:
    start, end = _window(tele.manifest)
    svc = world.outage_service_id

    def spans(inside: bool) -> list[Doc]:
        return [
            e
            for e in tele.events
            if e.get("service", {}).get("canonical_service_id") == svc
            and (start <= e["event_time"] < end) == inside
        ]

    during, before = spans(True), spans(False)
    assert during and before
    mean_during = sum(e["duration_ms"] for e in during) / len(during)
    mean_before = sum(e["duration_ms"] for e in before) / len(before)
    assert mean_during > 3 * mean_before
    assert any(e["outcome"] in ERRORS for e in during)


def test_tool_and_service_identity_matches_seeded_entities(
    world: DemoWorld, tele: DemoTelemetry
) -> None:
    tools = {t["id"]: t for t in world.tools}
    services = {s["id"] for s in world.services}
    mcp_ids = {m["id"] for m in world.mcp_servers}
    tool_spans = service_spans = mcp_spans = 0
    for e in tele.events:
        tool, svc, mcp = e.get("tool"), e.get("service"), e.get("mcp_server_ref")
        if tool is not None:
            tool_spans += 1
            seeded = tools[tool["canonical_tool_id"]]
            assert tool["tool_name"] == seeded["display_name"]
            assert tool["external_tool_id"]
            assert e["span_kind"] == "tool_call"
            assert mcp == seeded.get("mcp_server_ref")
        else:
            assert mcp is None
        if svc is not None:
            service_spans += 1
            assert svc["canonical_service_id"] in services
            assert svc["external_service_id"]
        if mcp is not None:
            mcp_spans += 1
            assert mcp in mcp_ids
        if e["span_kind"] in {"request", "agent_run", "model_call", "retrieval", "error"}:
            assert tool is None and svc is None and mcp is None
    assert tool_spans and service_spans and mcp_spans


def test_tool_service_pairing_follows_depends_on(world: DemoWorld, tele: DemoTelemetry) -> None:
    deps = {
        (r["source_id"], r["target_id"])
        for r in world.relations
        if r["relation_type"] == "depends_on"
    }
    for e in tele.events:
        if "tool" in e and "service" in e:
            assert (e["tool"]["canonical_tool_id"], e["service"]["canonical_service_id"]) in deps


def test_all_agents_present_including_telemetry_only(world: DemoWorld, tele: DemoTelemetry) -> None:
    seen = {e["canonical_agent_id"] for e in tele.events}
    assert {a["id"] for a in world.agents} <= seen
    assert set(world.undeclared_agent_ids) <= seen
    assert len(world.undeclared_agent_ids) == 4
    assert seen == {a["id"] for a in world.agents} | set(world.undeclared_agent_ids)
    catalog_ids = {a["id"] for a in world.agents}
    assert not (set(world.undeclared_agent_ids) & catalog_ids)


def test_cost_records_exist_for_curated_agents(world: DemoWorld, tele: DemoTelemetry) -> None:
    costed = {c["canonical_agent_id"] for c in tele.costs}
    assert {a["id"] for a in world.agents} <= costed
    event_ids = {e["event_id"] for e in tele.events}
    assert all(set(c["event_ids"]) <= event_ids for c in tele.costs)


def test_manifest_function_matches_embedded_manifest(world: DemoWorld, tele: DemoTelemetry) -> None:
    assert incident_manifest(world, SEED) == tele.manifest


def test_determinism_and_files(world: DemoWorld, tmp_path: Path) -> None:
    for name in ("a", "b", "c"):
        seed = 2 if name == "c" else SEED
        t = build_demo_telemetry(build_demo_world("commercial"), seed)
        write_demo_telemetry(t, tmp_path / name)
        write_incident_manifest(t.manifest, tmp_path / name / "incident-manifest.json")
    files = ("telemetry.ndjson", "cost.ndjson", "incident-manifest.json")
    a, b, c = ({f: sha256_of(tmp_path / n / f) for f in files} for n in ("a", "b", "c"))
    assert a == b
    assert a["telemetry.ndjson"] != c["telemetry.ndjson"]
    assert read_json(tmp_path / "a" / "incident-manifest.json")["service_id"] == (
        world.outage_service_id
    )


def test_volume_parameters_scale_output(world: DemoWorld, tele: DemoTelemetry) -> None:
    small = build_demo_telemetry(
        world, SEED, traces_per_agent_day=1, baseline_traces=2, incident_traces=3
    )
    assert len(small.events) < len(tele.events)
    assert set(small.manifest["downstream_agent_ids"]) == set(world.downstream_agent_ids)
