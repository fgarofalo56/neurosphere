"""Emulator smoke test (needs `docker compose up -d --wait cosmos`)."""

from __future__ import annotations

import json
import os

import pytest

from graph_benchmark import EMULATOR_LABEL, WORKLOADS, run_benchmark, write_evidence

pytestmark = pytest.mark.integration

ENDPOINT = os.environ.get("NS_COSMOS_EMULATOR_ENDPOINT", "http://localhost:8081")


def test_emulator_benchmark_produces_labelled_evidence(tmp_path):
    result = run_benchmark(
        ENDPOINT, "emulator_key", nodes=60, iterations=3, warmup=1, hub_degree=40
    )
    assert result.mode == "emulator"
    assert len(result.cells) == len(WORKLOADS) * 3
    assert {c.variant for c in result.cells} == {"flat", "hier2", "hier3"}
    assert result.all_correct, [c.correctness["violations"] for c in result.cells]
    assert all(c.latency["p95_ms"] > 0 for c in result.cells)
    jpath, mpath = write_evidence(result, tmp_path, EMULATOR_LABEL)
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert data["label"] == "emulator, bounded feasibility"
    assert set(data["p95_ms_by_workload"]) == set(WORKLOADS)
    assert data["environment"]["azure_cosmos_sdk_version"] != "not-installed"
    assert "request_charge" not in jpath.read_text(encoding="utf-8")
    assert EMULATOR_LABEL in mpath.read_text(encoding="utf-8")
