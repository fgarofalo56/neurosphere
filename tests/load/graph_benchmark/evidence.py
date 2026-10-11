"""Evidence writer: JSON + Markdown, labelled, with RU guarded off for the emulator."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .runner import BenchmarkResult

EMULATOR_LABEL = "emulator, bounded feasibility"
EMULATOR_UNMEASURED = (
    "Request units (RU): UNMEASURED (the emulator has no RU accounting)",
    "Index policy: UNMEASURED (the emulator does not reproduce range or composite indexes)",
    "Throttling (HTTP 429): UNMEASURED (the emulator does not throttle)",
    "Cross-partition fan-out cost: UNMEASURED (no per-partition cost model)",
)
DISCLAIMER = (
    "Latency here is local emulator latency. No cost, SLA, throughput or performance "
    "guarantee is made or implied. The live run against a real account (gate G03) is "
    "still required."
)
_FORBIDDEN_KEYS = ("ru", "request_charge", "request_units", "ru_consumed", "ru_per_sec")


def _walk_keys(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def build_payload(result: BenchmarkResult, label: str) -> dict[str, Any]:
    if result.mode == "emulator" and label != EMULATOR_LABEL:
        raise ValueError(f"emulator evidence must be labelled exactly {EMULATOR_LABEL!r}")
    cells = [asdict(c) for c in result.cells]
    if result.mode == "emulator":
        for c in cells:
            c.pop("request_charge", None)  # never present on emulator evidence
    payload: dict[str, Any] = {
        "gate": "G03",
        "label": label,
        "mode": result.mode,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": result.environment,
        "parameters": result.parameters,
        "p95_ms_by_workload": result.p95_by_workload(),
        "all_bounded_results_correct": result.all_correct,
        "cells": cells,
        "disclaimer": DISCLAIMER,
    }
    if result.mode == "emulator":
        payload["unmeasured"] = list(EMULATOR_UNMEASURED)
        bad = [k for k in _walk_keys(payload) if k.lower() in _FORBIDDEN_KEYS]
        if bad:
            raise ValueError(f"RU figures must not appear in emulator evidence: {bad}")
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    env, par = payload["environment"], payload["parameters"]
    lines = [
        f"# G03 graph partition and traversal benchmark: {payload['label']}",
        "",
        f"Label: **{payload['label']}**",
        "",
        f"Generated (UTC): {payload['generated_utc']}",
        "",
        "## Run parameters",
        "",
        f"- Mode: {payload['mode']}; credential mode: {env['credential_mode']}",
        f"- azure-cosmos SDK: {env['azure_cosmos_sdk_version']}; Python {env['python']}",
    ]
    if "emulator" in env:
        em = env["emulator"]
        lines.append(
            f"- Emulator image: {em['image']} (digest {em['digest']}, id {em['image_id']})"
        )
    lines += [
        f"- Seed {par['seed']}; nodes per workload {par['nodes']}; "
        f"edges per node {par['edges_per_node']}; "
        f"domains {par['domains']}; skew factor {par['skew_factor']}; "
        f"hub degree {par['hub_degree']}",
        f"- Iterations {par['iterations']} (+{par['warmup']} warm-up discarded)",
        f"- Budget (Budget contract): {json.dumps(par['budget'], sort_keys=True)}",
        f"- Partition variants: {json.dumps(par['variants'], sort_keys=True)}",
        "",
        "## Bounded traversal p95 by workload",
        "",
        "| Workload | Variant | Partition key | Nodes | Edges | p50 ms | p95 ms | Queries/trav. | "
        "Truncation | Bounded result correct |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in payload["cells"]:
        trunc = ", ".join(f"{k}:{v}" for k, v in c["truncation_counts"].items()) or "none"
        lines.append(
            f"| {c['workload']} | {c['variant']} | {' + '.join(c['partition_paths'])} | "
            f"{c['documents']['nodes']} | {c['documents']['edges']} | {c['latency']['p50_ms']} | "
            f"{c['latency']['p95_ms']} | {c['queries_per_traversal_mean']} | {trunc} | "
            f"{'yes' if c['correctness']['passed'] else 'NO'} |"
        )
    if payload["mode"] == "live":
        lines += ["", "## Measured request charge (live)", ""]
        for c in payload["cells"]:
            if c.get("request_charge"):
                charge = json.dumps(c["request_charge"])
                lines.append(f"- {c['workload']} / {c['variant']}: {charge}")
    violations = [
        (c["workload"], c["variant"], c["correctness"]["violations"])
        for c in payload["cells"]
        if c["correctness"]["violations"]
    ]
    lines += ["", "## Bounded-result correctness", ""]
    lines.append(
        "All traversals stayed within the depth, fan-out, node, edge and time budgets and matched "
        "the reference traversal."
        if not violations
        else "Violations: " + json.dumps(violations)
    )
    if payload["mode"] == "emulator":
        lines += ["", "## Not measured", ""]
        lines += [f"- {item}" for item in payload["unmeasured"]]
    lines += ["", "## Disclaimer", "", payload["disclaimer"], ""]
    return "\n".join(lines)


def write_evidence(
    result: BenchmarkResult,
    out_dir: str | Path,
    label: str = EMULATOR_LABEL,
    *,
    when: date | None = None,
    slug: str | None = None,
) -> tuple[Path, Path]:
    """Write ``<slug>-<YYYY-MM-DD>.json`` and ``.md`` into ``out_dir``; returns both paths.

    ``slug`` defaults to ``emulator`` or ``live`` from the result mode.
    """
    payload = build_payload(result, label)
    stem = f"{slug or result.mode}-{(when or datetime.now(UTC).date()).isoformat()}"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jpath, mpath = out / f"{stem}.json", out / f"{stem}.md"
    jpath.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    mpath.write_text(render_markdown(payload), encoding="utf-8")
    return jpath, mpath
