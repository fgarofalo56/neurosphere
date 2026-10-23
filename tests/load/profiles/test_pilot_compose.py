"""Pilot profile against the compose emulators (PRP-21 item 1). Marked ``integration``.

Needs ``docker compose up -d --wait`` (Event Hubs emulator). Starts a local API with the ingest
edge, runs locust as an isolated uv subprocess for a SHORT bounded time and checks the evidence
JSON. It asserts the evidence is complete and the thresholds were evaluated, NOT that the pilot
met 1k events per second: pass/fail against the provisional thresholds is data, and a laptop may
legitimately miss it. A green run here is never evidence for enterprise or stress.

FAILS (never skips) when the emulator is unreachable. Results go to pytest's tmp dir, not docs/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .compose_pilot import run_pilot
from .definitions import PILOT

pytestmark = pytest.mark.integration

SHORT_RUN_SECONDS = 20


def test_pilot_run_writes_complete_evidence(tmp_path: Path) -> None:
    code, path, tail = run_pilot(tmp_path, duration_seconds=SHORT_RUN_SECONDS)
    assert path is not None, f"no evidence written (locust exit {code}):\n{tail}"
    doc = json.loads(path.read_text(encoding="utf-8"))

    assert doc["profile"] == "pilot"
    assert doc["not_evidence_for"] == ["enterprise", "stress"]
    assert doc["environment_label"] == (
        "compose (emulators), bounded feasibility only - not capacity evidence (G12)"
    )
    assert doc["git_sha"]
    assert doc["date"]
    assert doc["method"]
    assert doc["profile_definition"]["agents"] == PILOT.agents
    assert doc["profile_definition"]["sustained_events_per_second"] == 1_000

    measured = doc["measured"]
    for key in (
        "achieved_events_per_second",
        "error_counts_by_type",
        "error_ratio",
        "latency_ms",
        "duration_seconds",
        "requests",
        "events_accepted",
    ):
        assert key in measured, key
    assert measured["requests"] > 0, tail
    assert measured["events_sent"] > 0
    assert set(measured["latency_ms"]) >= {"p50", "p95", "p99"}
    assert measured["distinct_agents_emitted"] > 0
    assert doc["run_parameters"]["users"] == PILOT.default_users

    # Thresholds were evaluated, each with a boolean verdict (pass or fail is data here).
    names = {row["name"]: row for row in doc["thresholds"]}
    assert set(names) == {
        "achieved_events_per_second",
        "error_ratio",
        "request_latency_p95_ms",
    }
    assert all(isinstance(row["passed"], bool) for row in names.values())
    assert all(row["provisional"] is True for row in names.values())
    assert isinstance(doc["thresholds_all_passed"], bool)

    assert set(doc["scenarios"]) <= set(PILOT.scenario_weights)
    assert doc["domains"]["count"] > 0
    assert doc["emulator_limits"]["documented"]
    assert doc["emulator_limits"]["observed_in_this_run"]
    assert any("OPEN" in line for line in doc["open"])
