"""Offline tests: workloads, bounded traversal, correctness oracle, evidence writer."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from graph_benchmark import (
    EMULATOR_LABEL,
    VARIANTS,
    WORKLOADS,
    Budget,
    InMemoryGraphStore,
    bounded_traverse,
    check_correctness,
    generate,
    run_benchmark,
    write_evidence,
)

EMU = {"image": "test-image", "digest": "none", "image_id": "none"}


def _run(**kw):
    store = InMemoryGraphStore()
    return run_benchmark(
        "http://unused",
        store=store,
        nodes=60,
        iterations=4,
        warmup=1,
        hub_degree=40,
        emulator=EMU,
        **kw,
    ), store


def test_budget_enforces_contract_ceilings():
    with pytest.raises(ValueError):
        Budget(max_depth=6)
    with pytest.raises(ValueError):
        Budget(timeout_ms=0)
    assert Budget().to_dict()["limit"] == 25


@pytest.mark.parametrize("workload", WORKLOADS)
def test_datasets_deterministic_and_wellformed(workload):
    a, b = generate(workload, nodes=50, seed=7), generate(workload, nodes=50, seed=7)
    assert a.edges == b.edges
    ids = {n["id"] for n in a.nodes}
    assert all(e["src"] in ids and e["dst"] in ids for e in a.edges)
    assert len({e["id"] for e in a.edges}) == len(a.edges)


def test_workload_shapes():
    sk = generate("skewed", nodes=100, skew_factor=0.8)
    assert sum(n["domain"] == "domain-0" for n in sk.nodes) == 80
    hd = generate("high_degree", nodes=100, hub_degree=60)
    assert sum(e["src"] == "n-0" for e in hd.edges) >= 60
    cd = generate("cross_domain", nodes=50)
    assert all(e["domain"] != e["dst_domain"] for e in cd.edges)


def test_traversal_honors_budgets_and_flags_truncation():
    ds = generate("high_degree", nodes=100, hub_degree=80)
    store = InMemoryGraphStore()
    variant = VARIANTS["hier3"]
    c = store.create_container("t", variant)
    for d in ds.nodes + ds.edges:
        c.upsert(d)
    hub = ds.nodes[0]
    budget = Budget(limit=10, max_depth=2, max_nodes=30, max_edges=100)
    res = bounded_traverse(c, variant, hub, budget)
    assert "fanout" in res.truncated
    assert len(res.nodes) <= 30 and len(res.edges) <= 100 and res.max_fanout_seen <= 10
    assert check_correctness(ds, res, budget) == []
    # tampering is detected
    res.edges.append("e-not-real")
    assert check_correctness(ds, res, budget)


def test_timeout_budget_stops_traversal():
    ds = generate("cross_domain", nodes=50)
    store = InMemoryGraphStore()
    variant = VARIANTS["flat"]
    c = store.create_container("t", variant)
    for d in ds.nodes + ds.edges:
        c.upsert(d)
    ticks = iter(range(0, 10_000))
    res = bounded_traverse(
        c, variant, ds.nodes[0], Budget(timeout_ms=3), clock=lambda: next(ticks) / 1000
    )
    assert "timeout" in res.truncated


def test_fresh_containers_never_reused():
    store = InMemoryGraphStore()
    store.create_container("x", VARIANTS["flat"])
    with pytest.raises(ValueError):
        store.create_container("x", VARIANTS["flat"])
    result, st = _run()
    names = list(st.containers) or [c.container for c in result.cells]
    assert len(set(names)) == len(result.cells) == len(WORKLOADS) * len(VARIANTS)


def test_evidence_files_label_dates_and_no_ru(tmp_path):
    result, _ = _run()
    assert result.mode == "emulator" and result.all_correct
    j, m = write_evidence(result, tmp_path, EMULATOR_LABEL, when=date(2026, 10, 11))
    assert j.name == "emulator-2026-10-11.json" and m.name == "emulator-2026-10-11.md"
    data = json.loads(j.read_text(encoding="utf-8"))
    md = m.read_text(encoding="utf-8")
    assert data["label"] == EMULATOR_LABEL == "emulator, bounded feasibility"
    assert EMULATOR_LABEL in md
    assert set(data["p95_ms_by_workload"]) == set(WORKLOADS)
    assert len(data["cells"]) == 9
    for key in ("azure_cosmos_sdk_version", "emulator"):
        assert key in data["environment"]
    for key in ("budget", "skew_factor", "nodes", "iterations"):
        assert key in data["parameters"]
    assert all("documents" in c for c in data["cells"])
    # no RU figure anywhere: no RU-ish keys, and no digits on any line that mentions RU
    flat = json.dumps(data).lower()
    assert "request_charge" not in flat and '"ru"' not in flat
    for line in md.splitlines():
        if re.search(r"\bRU\b", line):
            assert not re.search(r"\d", line), line
    # unmeasured items are stated
    text = " ".join(data["unmeasured"])
    for needle in ("RU", "Index policy", "429", "Cross-partition"):
        assert needle in text and "UNMEASURED" in text
    assert "guarantee" in md


def test_emulator_label_is_enforced(tmp_path):
    result, _ = _run()
    with pytest.raises(ValueError, match="labelled exactly"):
        write_evidence(result, tmp_path, "live benchmark")


def test_emulator_evidence_rejects_ru_figures(tmp_path):
    result, _ = _run()
    result.cells[0].request_charge = {"mean": 3.2, "max": 5.0}
    j, _m = write_evidence(result, tmp_path, EMULATOR_LABEL, when=date(2026, 10, 11))
    assert "request_charge" not in j.read_text(encoding="utf-8")


def test_live_mode_may_carry_request_charge(tmp_path):
    result, _ = _run()
    result.mode = "live"
    result.cells[0].request_charge = {"mean": 3.2, "max": 5.0}
    j, m = write_evidence(result, tmp_path, "live, Commercial", when=date(2026, 10, 11))
    assert j.name.startswith("live-") and "request_charge" in j.read_text(encoding="utf-8")
    assert "Measured request charge" in m.read_text(encoding="utf-8")
