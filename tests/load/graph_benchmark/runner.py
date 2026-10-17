"""Benchmark runner: fresh containers, data load, bounded traversals, p95."""

from __future__ import annotations

import platform
import subprocess
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .model import VARIANTS, Budget, TraversalResult, latency_stats
from .provision import Provisioner
from .store import CREDENTIAL_MODES, GraphStore, SdkGraphStore, sdk_version
from .traversal import bounded_traverse, check_correctness
from .workloads import WORKLOADS, Dataset, generate

DEFAULT_EMULATOR_IMAGE = "mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest"


@dataclass
class CellResult:
    workload: str
    variant: str
    partition_paths: list[str]
    container: str
    documents: dict[str, int]
    latency: dict[str, float | int]
    correctness: dict[str, Any]
    truncation_counts: dict[str, int]
    queries_per_traversal_mean: float
    request_charge: dict[str, float] | None = None  # live only; never set on the emulator


@dataclass
class BenchmarkResult:
    mode: str  # "emulator" | "live"
    environment: dict[str, Any]
    parameters: dict[str, Any]
    cells: list[CellResult] = field(default_factory=list)

    def p95_by_workload(self, variant: str | None = None) -> dict[str, float]:
        """p95 bounded-traversal latency (ms) per workload for one variant (default: first run)."""
        if not self.cells:
            return {}
        variant = variant or self.cells[0].variant
        return {c.workload: float(c.latency["p95_ms"]) for c in self.cells if c.variant == variant}

    @property
    def all_correct(self) -> bool:
        return all(c.correctness["passed"] for c in self.cells)


def describe_emulator_image(image: str = DEFAULT_EMULATOR_IMAGE) -> dict[str, str]:
    """Best-effort image id/digest from the local docker daemon ('unknown' if unavailable)."""
    out = {"image": image, "digest": "unknown", "image_id": "unknown"}
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}} {{json .RepoDigests}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            image_id, _, digests = proc.stdout.strip().partition(" ")
            out["image_id"] = image_id
            out["digest"] = digests or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def run_benchmark(
    endpoint: str,
    credential_mode: str = "emulator_key",
    *,
    workloads: tuple[str, ...] = WORKLOADS,
    variants: tuple[str, ...] = ("flat", "hier2", "hier3"),
    nodes: int = 200,
    edges_per_node: int = 3,
    domains: int = 8,
    skew_factor: float = 0.8,
    hub_degree: int = 200,
    iterations: int = 20,
    warmup: int = 2,
    budget: Budget | None = None,
    seed: int = 42,
    key: str | None = None,
    database_prefix: str = "g03-bench",
    cleanup: bool = True,
    measure_request_charge: bool | None = None,
    load_workers: int = 16,
    emulator: dict[str, str] | None = None,
    store: GraphStore | None = None,
    provisioner: Provisioner | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkResult:
    """Run the G03 benchmark and return a result object.

    ``credential_mode``: ``emulator_key`` (emulator, http, no TLS verify, no RU) or
    ``default_azure_credential`` (live; RU captured when ``measure_request_charge`` is true,
    which defaults to true for live). ``store`` injects a pre-built GraphStore (tests).
    ``provisioner`` (live only) creates/deletes the database and containers through the control
    plane because Entra data-plane tokens cannot.
    Fresh database and containers are created every call; none is ever reused.
    """
    if credential_mode not in CREDENTIAL_MODES:
        raise ValueError(f"credential_mode must be one of {CREDENTIAL_MODES}")
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown partition variants {unknown}; expected {sorted(VARIANTS)}")
    budget = budget or Budget()
    live = credential_mode != "emulator_key"
    measure = live if measure_request_charge is None else (measure_request_charge and live)
    run_id = f"{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    database = f"{database_prefix}-{run_id}"
    own_store = store is None
    if store is None:
        store = SdkGraphStore(
            endpoint,
            credential_mode,
            database,
            key=key,
            measure_request_charge=measure,
            provisioner=provisioner,
        )
    environment: dict[str, Any] = {
        "run_id": run_id,
        "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "credential_mode": credential_mode,
        "database": store.database,
        "azure_cosmos_sdk_version": sdk_version(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    if not live:
        environment["emulator"] = emulator or describe_emulator_image()
    result = BenchmarkResult(
        mode="live" if live else "emulator",
        environment=environment,
        parameters={
            "workloads": list(workloads),
            "variants": {v: list(VARIANTS[v].paths) for v in variants},
            "nodes": nodes,
            "edges_per_node": edges_per_node,
            "domains": domains,
            "skew_factor": skew_factor,
            "hub_degree": hub_degree,
            "iterations": iterations,
            "warmup": warmup,
            "seed": seed,
            "budget": budget.to_dict(),
            "charge_capture": measure,
        },
    )
    try:
        for workload in workloads:
            ds = generate(
                workload,
                nodes=nodes,
                edges_per_node=edges_per_node,
                domains=domains,
                skew_factor=skew_factor,
                hub_degree=hub_degree,
                seed=seed,
            )
            for vname in variants:
                result.cells.append(
                    _run_cell(
                        store,
                        ds,
                        vname,
                        run_id,
                        iterations,
                        warmup,
                        budget,
                        measure,
                        clock,
                        load_workers,
                    )
                )
    finally:
        if own_store:
            store.close(cleanup=cleanup)
    return result


def _run_cell(
    store: GraphStore,
    ds: Dataset,
    vname: str,
    run_id: str,
    iterations: int,
    warmup: int,
    budget: Budget,
    measure: bool,
    clock: Callable[[], float],
    load_workers: int = 16,
) -> CellResult:
    variant = VARIANTS[vname]
    container = store.create_container(f"{ds.workload}-{vname}-{run_id}".replace("_", "-"), variant)
    with ThreadPoolExecutor(max_workers=max(1, load_workers)) as pool:
        # list() surfaces any load error; all data is loaded before any traversal runs.
        list(pool.map(container.upsert, [*ds.nodes, *ds.edges]))
    node_by_id = {n["id"]: n for n in ds.nodes}
    runs: list[TraversalResult] = []
    violations: list[str] = []
    for i in range(warmup + iterations):
        root = node_by_id[ds.roots[i % len(ds.roots)]]
        res = bounded_traverse(container, variant, root, budget, clock=clock)
        if i < warmup:
            continue
        runs.append(res)
        violations += check_correctness(ds, res, budget)
    truncation: dict[str, int] = {}
    for r in runs:
        for t in r.truncated:
            truncation[t] = truncation.get(t, 0) + 1
    charges = [r.request_charge for r in runs if r.request_charge is not None]
    return CellResult(
        workload=ds.workload,
        variant=vname,
        partition_paths=list(variant.paths),
        container=container.name,
        documents={"nodes": len(ds.nodes), "edges": len(ds.edges)},
        latency=latency_stats([r.elapsed_ms for r in runs]),
        correctness={
            "checked": len(runs),
            "passed": not violations,
            "violations": sorted(set(violations)),
            "mean_nodes_returned": round(sum(len(r.nodes) for r in runs) / max(1, len(runs)), 2),
            "mean_edges_returned": round(sum(len(r.edges) for r in runs) / max(1, len(runs)), 2),
        },
        truncation_counts=dict(sorted(truncation.items())),
        queries_per_traversal_mean=round(sum(r.queries for r in runs) / max(1, len(runs)), 2),
        request_charge=(
            {"mean": round(sum(charges) / len(charges), 3), "max": round(max(charges), 3)}
            if measure and charges
            else None
        ),
    )
