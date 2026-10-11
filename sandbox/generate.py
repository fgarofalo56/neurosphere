"""CLI and orchestration: ``python -m sandbox.generate --seed N --profile tiny --cloud commercial``.

Streams every record to NDJSON; only one hour of trace events is ever held in memory (plus
the bad-event hold-back of at most ``late_max_seconds`` of events).
"""

from __future__ import annotations

import argparse
import bisect
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sandbox import __version__, catalog
from sandbox.bad_events import BadEventInjector
from sandbox.config import (
    CLOUDS,
    DEFAULT_EPOCH,
    PROFILES,
    BadEventRates,
    GenerateConfig,
    with_overrides,
)
from sandbox.ids import fmt_ts_s
from sandbox.output import NdjsonWriter, write_json
from sandbox.traces import TraceGenerator
from sandbox.world import DAY_MS, World

Doc = dict[str, Any]
HOUR_MS = 3_600_000

CATALOG_FILES: tuple[tuple[str, Callable[[World], Iterable[Doc]]], ...] = (
    ("domains.ndjson", catalog.iter_domains),
    ("owners.ndjson", catalog.iter_owners),
    ("persons.ndjson", catalog.iter_persons),
    ("model_deployments.ndjson", catalog.iter_models),
    ("grounding_sources.ndjson", catalog.iter_sources),
    ("tools.ndjson", catalog.iter_tools),
    ("agents.ndjson", catalog.iter_agents),
    ("agent_versions.ndjson", catalog.iter_agent_versions),
    ("relations.ndjson", catalog.iter_relations),
)
MANIFEST_VERSION = "1.0"


def _anomaly_manifest(world: World) -> Doc:
    items: list[Doc] = []
    for a in world.anomalies:
        window = {
            "start": fmt_ts_s(world.epoch_ms + a.start_day * DAY_MS),
            "end": fmt_ts_s(world.epoch_ms + a.end_day * DAY_MS),
        }
        item: Doc = {
            "anomaly_id": f"anom-{a.type}-{a.seq:03d}",
            "type": a.type,
            "affected_ids": [world.agent_id(i) for i in a.agents],
            "window": window,
            "label": "candidate" if a.type == "duplicate_agent_candidates" else "ground_truth",
            "details": a.details,
        }
        items.append(item)
    cfg = world.cfg
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": "sandbox-anomaly-manifest",
        "generator_version": __version__,
        "seed": cfg.seed,
        "profile": cfg.profile.name,
        "cloud": cfg.cloud,
        "epoch": cfg.epoch,
        "anomalies": items,
    }


def generate(cfg: GenerateConfig, out: Path) -> Doc:
    """Write the full data set for ``cfg`` into ``out`` and return the run manifest."""
    out.mkdir(parents=True, exist_ok=True)
    world = World(cfg)
    counts: dict[str, int] = {}

    for name, fn in CATALOG_FILES:
        with NdjsonWriter(out / name) as w:
            for doc in fn(world):
                w.write_doc(doc)
        counts[name] = w.count

    gen = TraceGenerator(world)
    with (
        NdjsonWriter(out / "telemetry.ndjson") as tele,
        NdjsonWriter(out / "cost.ndjson") as cost,
        NdjsonWriter(out / "bad-event-manifest.ndjson") as bad_entries,
    ):
        injector = BadEventInjector(cfg.seed, cfg.rates, bad_entries.write_doc)

        def drain(t_ms: int, doc: Doc) -> None:
            for line in injector.feed(t_ms, doc):
                tele.write_line(line)

        buffer: list[tuple[int, str, Doc]] = []
        for day in range(world.days):
            day_start = world.epoch_ms + day * DAY_MS
            starts: list[tuple[int, int, int]] = []
            for agent in range(len(world.agents)):
                for k in range(gen.trace_count(agent, day)):
                    starts.append((gen.start_offset_ms(agent, day, k), agent, k))
            starts.sort()
            pos = 0
            for hour in range(24):
                hour_end = day_start + (hour + 1) * HOUR_MS
                hour_costs: list[Doc] = []
                while pos < len(starts) and starts[pos][0] < (hour + 1) * HOUR_MS:
                    offset, agent, k = starts[pos]
                    pos += 1
                    events, costs = gen.build(agent, day, k, day_start + offset)
                    buffer.extend(events)
                    hour_costs.extend(costs)
                buffer.sort(key=lambda e: (e[0], e[1]))
                cut = bisect.bisect_left(buffer, hour_end, key=lambda e: e[0])
                for t_ms, _, doc in buffer[:cut]:
                    drain(t_ms, doc)
                del buffer[:cut]
                hour_costs.sort(key=lambda c: (c["recorded_at"], c["cost_id"]))
                for c in hour_costs:
                    cost.write_doc(c)
        for t_ms, _, doc in buffer:
            drain(t_ms, doc)
        for line in injector.flush():
            tele.write_line(line)

    counts["telemetry.ndjson"] = tele.count
    counts["cost.ndjson"] = cost.count
    counts["bad-event-manifest.ndjson"] = bad_entries.count

    dup = injector.counts["duplicate"]
    mal = injector.counts["malformed"]
    rates = cfg.rates
    write_json(
        out / "bad-event-manifest.json",
        {
            "manifest_version": MANIFEST_VERSION,
            "kind": "sandbox-bad-event-manifest",
            "seed": cfg.seed,
            "cloud": cfg.cloud,
            "telemetry_file": "telemetry.ndjson",
            "entries_file": "bad-event-manifest.ndjson",
            "rates": {
                "duplicate": rates.duplicate,
                "out_of_order": rates.out_of_order,
                "malformed": rates.malformed,
                "missing_optional": rates.missing_optional,
                "late_min_seconds": rates.late_min_seconds,
                "late_max_seconds": rates.late_max_seconds,
            },
            "counts": {
                "duplicate": dup,
                "out_of_order": injector.counts["out_of_order"],
                "malformed": mal,
                "missing_optional": injector.counts["missing_optional"],
            },
            "expected": {
                "total_lines": tele.count,
                "duplicate_lines": dup,
                "malformed_lines": mal,
                "valid_distinct_events": tele.count - dup - mal,
            },
        },
    )
    write_json(out / "anomaly-manifest.json", _anomaly_manifest(world))

    run: Doc = {
        "manifest_version": MANIFEST_VERSION,
        "kind": "sandbox-run-manifest",
        "generator_version": __version__,
        "seed": cfg.seed,
        "profile": cfg.profile.name,
        "cloud": cfg.cloud,
        "epoch": cfg.epoch,
        "customer_id": cfg.customer,
        "environment": "sandbox",
        "days": cfg.profile.days,
        "files": {name: {"records": n} for name, n in sorted(counts.items())},
    }
    write_json(out / "run-manifest.json", run)
    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sandbox.generate",
        description="Generate deterministic synthetic NeuroSphere sandbox data (NDJSON).",
    )
    p.add_argument(
        "--seed", type=int, required=True, help="integer seed; same seed+epoch => identical bytes"
    )
    p.add_argument("--profile", choices=sorted(PROFILES), default="tiny")
    p.add_argument(
        "--cloud", choices=CLOUDS, required=True, help="one cloud per output; never mixed"
    )
    p.add_argument(
        "--epoch", default=DEFAULT_EPOCH, help="start time, RFC 3339 UTC (YYYY-MM-DDTHH:MM:SSZ)"
    )
    p.add_argument("--out", type=Path, default=Path("temp/sandbox"), help="output directory")
    p.add_argument("--agents", type=int, help="override agent count (incl. sub-agents)")
    p.add_argument("--domains", type=int, help="override domain count")
    p.add_argument("--days", type=int, help="override window length in days")
    p.add_argument(
        "--traces-per-agent-day", type=float, help="override mean traces per agent per day"
    )
    p.add_argument("--duplicate-rate", type=float, help="fraction of events duplicated")
    p.add_argument("--out-of-order-rate", type=float, help="fraction of events delivered late")
    p.add_argument("--malformed-rate", type=float, help="fraction of events schema-violating")
    p.add_argument("--missing-optional-rate", type=float, help="fraction missing optional fields")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = with_overrides(
        PROFILES[args.profile],
        agents=args.agents,
        domains=args.domains,
        days=args.days,
        traces_per_agent_day=args.traces_per_agent_day,
    )
    base = BadEventRates()
    rates = BadEventRates(
        duplicate=base.duplicate if args.duplicate_rate is None else args.duplicate_rate,
        out_of_order=base.out_of_order
        if args.out_of_order_rate is None
        else args.out_of_order_rate,
        malformed=base.malformed if args.malformed_rate is None else args.malformed_rate,
        missing_optional=(
            base.missing_optional
            if args.missing_optional_rate is None
            else args.missing_optional_rate
        ),
    )
    cfg = GenerateConfig(
        seed=args.seed, profile=profile, cloud=args.cloud, epoch=args.epoch, rates=rates
    )
    run = generate(cfg, args.out)
    sys.stdout.write(
        f"wrote {args.out} (profile={profile.name}, cloud={cfg.cloud}, seed={cfg.seed})\n"
    )
    for name, info in run["files"].items():
        sys.stdout.write(f"  {name}: {info['records']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
