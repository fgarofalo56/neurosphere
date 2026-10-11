"""Seeded anomalies: manifest completeness and measurable effect in the data (pilot profile)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sandbox.tests.support import read_json, read_ndjson

TYPES = {"cost_spike", "latency_regression", "unused_agent", "duplicate_agent_candidates"}


def _anomalies(directory: Path) -> list[dict[str, Any]]:
    manifest = read_json(directory / "anomaly-manifest.json")
    anomalies: list[dict[str, Any]] = manifest["anomalies"]
    return anomalies


def test_every_type_present_in_pilot(pilot_dir: Path) -> None:
    anomalies = _anomalies(pilot_dir)
    by_type = defaultdict(list)
    for a in anomalies:
        by_type[a["type"]].append(a)
    assert set(by_type) == TYPES
    assert all(len(v) >= 1 for v in by_type.values())
    ids = [a["anomaly_id"] for a in anomalies]
    assert len(ids) == len(set(ids))
    agents = {d["id"] for d in read_ndjson(pilot_dir / "agents.ndjson")}
    for a in anomalies:
        assert a["window"]["start"] < a["window"]["end"]
        assert a["affected_ids"] and set(a["affected_ids"]) <= agents


def test_every_type_present_in_tiny(tiny_dir: Path) -> None:
    assert {a["type"] for a in _anomalies(tiny_dir)} == TYPES


def test_duplicates_are_candidates_with_real_overlap(pilot_dir: Path) -> None:
    grounding: dict[str, set[str]] = defaultdict(set)
    for rel in read_ndjson(pilot_dir / "relations.ndjson"):
        if rel["relation_type"] == "grounded_by" and rel["status"] == "asserted":
            grounding[rel["source_id"]].add(rel["target_id"])
    dups = [a for a in _anomalies(pilot_dir) if a["type"] == "duplicate_agent_candidates"]
    assert dups
    for a in dups:
        assert a["label"] == "candidate"
        assert a["details"]["label"] == "candidate"
        assert a["details"]["auto_merge"] is False
        left, right = a["affected_ids"]
        shared = grounding[left] & grounding[right]
        assert len(shared) >= 2
        assert set(a["details"]["shared_grounding_source_ids"]) <= shared


def test_unused_agents_emit_no_telemetry(pilot_dir: Path) -> None:
    unused = {
        i for a in _anomalies(pilot_dir) if a["type"] == "unused_agent" for i in a["affected_ids"]
    }
    seen = {d.get("canonical_agent_id") for d in read_ndjson(pilot_dir / "telemetry.ndjson")}
    assert unused and not (unused & seen)


def test_cost_spike_is_visible_in_cost_records(pilot_dir: Path) -> None:
    spikes = [a for a in _anomalies(pilot_dir) if a["type"] == "cost_spike"]
    per_day: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for c in read_ndjson(pilot_dir / "cost.ndjson"):
        if c["observation_source"] == "gateway":
            per_day[c["canonical_agent_id"]][c["usage_start"][:10]] += Decimal(c["amount"])
    for a in spikes:
        agent = a["affected_ids"][0]
        start, end = a["window"]["start"][:10], a["window"]["end"][:10]
        inside = [v for d, v in per_day[agent].items() if start <= d < end]
        outside = [v for d, v in per_day[agent].items() if not start <= d < end]
        assert inside and outside
        assert max(inside) > 3 * (sum(outside) / len(outside)), agent


def test_latency_regression_is_visible_in_durations(pilot_dir: Path) -> None:
    regs = [a for a in _anomalies(pilot_dir) if a["type"] == "latency_regression"]
    durations: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for e in read_ndjson(pilot_dir / "telemetry.ndjson"):
        if (
            e.get("span_kind") == "model_call"
            and e.get("outcome") == "success"
            and "duration_ms" in e
        ):
            durations[e["canonical_agent_id"]].append((e["event_time"], e["duration_ms"]))
    for a in regs:
        agent = a["affected_ids"][0]
        start = a["window"]["start"]
        before = [d for t, d in durations[agent] if t < start]
        after = [d for t, d in durations[agent] if t >= start]
        assert before and after
        assert sum(after) / len(after) > 1.8 * (sum(before) / len(before)), agent
