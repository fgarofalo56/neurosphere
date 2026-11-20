"""Telemetry, cost and the scripted incident for the curated demo world (PRP-71 item 2).

Builds ``TelemetryEvent`` spans and ``CostRecord`` observations directly from a
:class:`sandbox.demo.build.DemoWorld` (the generic generator world cannot take curated
entities). Everything is seeded: each trace draws from its own RNG stream keyed on
``(seed, agent, phase, n)``, iteration is sorted, and no wall clock is read, so one
``(world, seed, volume)`` always yields the same bytes.

Time layout, all relative to the END of the seeded window (so it stays recent after the seed
rebases the epoch)::

    [epoch ........................ end-2h) [end-2h, end-1h)  [end-1h, end)
     background traffic, N per day            baseline hour     INCIDENT hour

The incident hour is the last hour. In it every trace of an agent that depends on the outage
service reaches that service, and spans bound to the service fail (``error``/``timeout``) with
sharply raised latency. The model call that was waiting on the failed result is abandoned and
recorded with the same outcome, and the agent's run and request then fail too. The abandoned
``model_call`` is what the product measures: the aggregates worker counts ``model_call`` spans
only (``neurosphere_workers.aggregates.mapping``), so without it the incident is invisible in
the hourly error rate. With it the agent's rate crosses the aggregate health thresholds
(degraded at 0.05, failing at 0.25). Agents that do not depend on the service keep a
``model_call`` error rate of zero; their rare background failure is a single tool span.

Public API: :func:`build_demo_telemetry`, :func:`write_demo_telemetry`,
:func:`incident_manifest`, :func:`write_incident_manifest`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent

from sandbox.config import (
    PRICE_EFFECTIVE_DATE,
    PRICE_VERSION,
    SCHEMA_VERSION,
    ModelSpec,
    parse_epoch,
)
from sandbox.costs import price
from sandbox.demo.build import DemoWorld
from sandbox.ids import digest_hex, fmt_ts, fmt_ts_s, rng_for
from sandbox.output import NdjsonWriter, write_json
from sandbox.world import DAY_MS

Doc = dict[str, Any]

HOUR_MS = 3_600_000
MANIFEST_VERSION = "1.0"

DEFAULT_TRACES_PER_AGENT_DAY = 2
DEFAULT_BASELINE_TRACES = 4
DEFAULT_INCIDENT_TRACES = 6
"""Defaults: about 6k events for the 36 agents over 7 days (modest for an Event Hubs seed)."""

P_BACKGROUND_TOOL_ERROR = 0.01
"""Background failure rate: a single tool span, never the run (stays far below health 0.05)."""
P_INCIDENT_FAIL = 0.9
INCIDENT_MAX_ATTEMPTS = 3
"""Calls an agent makes to the failing service before it gives up (the first and two retries).
Each failed attempt abandons one model call, which is what lifts the measured error rate far
enough to show at domain grain as well (a domain holds one downstream agent among many)."""
INCIDENT_LATENCY_FACTOR = 8
HEALTH_DEGRADED_ERROR_RATE = 0.05  # mirrors neurosphere_core.aggregates.subject
HEALTH_FAILING_ERROR_RATE = 0.25
P_DELEGATE = 0.5
"""Share of a parent's traces that hand off to each of its paired children."""
MAX_DELEGATION_DEPTH = 2
_TRACE_TAIL_MS = 40_000  # a trace starts at least this long before the end of its phase

# Synthetic price/latency per demo model name (USD per 1000 tokens; not real list prices).
_SPECS: dict[str, tuple[str, str, Decimal, Decimal, int, float]] = {
    "gpt-4o": ("azure_openai", "2024-11-20", Decimal("0.0025"), Decimal("0.0100"), 700, 22.0),
    "gpt-4o-mini": ("azure_openai", "2024-07-18", Decimal("0.0002"), Decimal("0.0006"), 350, 9.0),
    "text-embedding-3-large": ("azure_openai", "1", Decimal("0.00013"), Decimal("0"), 120, 0.0),
    "phi-4": ("microsoft", "1", Decimal("0.0001"), Decimal("0.0004"), 250, 6.0),
}


@dataclass(frozen=True, slots=True)
class _Actor:
    agent_id: str
    external_id: str
    domain_id: str
    model_id: str
    tool_ids: tuple[str, ...]
    service_ids: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(slots=True)
class _Trace:
    """Mutable state of one trace: its id, span counter and spans so far."""

    trace: str
    incident: bool
    seq: int = 0
    evs: list[Doc] = field(default_factory=list)


@dataclass(slots=True)
class DemoTelemetry:
    """Telemetry events (sorted by event time) and cost records for one demo world."""

    events: list[Doc] = field(default_factory=list)
    costs: list[Doc] = field(default_factory=list)
    manifest: Doc = field(default_factory=dict)


def _slug(canonical: str) -> str:
    return canonical.rsplit(":", 1)[1]


def _spec(model: Doc) -> ModelSpec:
    provider, version, p_in, p_out, base, per_tok = _SPECS.get(
        model["model_name"],
        ("azure_openai", model["model_version"], Decimal("0.001"), Decimal("0.004"), 500, 12.0),
    )
    return ModelSpec(
        slug=_slug(model["id"]),
        provider=provider,
        model_name=model["model_name"],
        model_version=model["model_version"] or version,
        price_in=p_in,
        price_out=p_out,
        base_latency_ms=base,
        ms_per_output_token=per_tok,
    )


def _windows(world: DemoWorld) -> tuple[int, int, int, int]:
    """(epoch, baseline_start, incident_start, end) in epoch milliseconds."""
    epoch = parse_epoch(world.epoch)
    end = epoch + world.days * DAY_MS
    return epoch, end - 2 * HOUR_MS, end - HOUR_MS, end


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


class _Builder:
    def __init__(
        self,
        world: DemoWorld,
        seed: int,
        per_day: int,
        baseline: int,
        incident: int,
    ) -> None:
        self.w = world
        self.seed = seed
        self.per_day = per_day
        self.baseline = baseline
        self.incident = incident
        self.epoch, self.base_start, self.inc_start, self.end = _windows(world)
        self.downstream = set(world.downstream_agent_ids)
        self.models = {m["id"]: _spec(m) for m in world.models}
        self.model_docs = {m["id"]: m for m in world.models}
        self.tools = {t["id"]: t for t in world.tools}
        self.tool_services: dict[str, tuple[str, ...]] = {}
        self.events: list[Doc] = []
        self.costs: list[Doc] = []
        self._actors = self._build_actors()
        self.actors = {a.agent_id: a for a in self._actors}
        children: dict[str, list[str]] = {}
        for parent, child in world.delegations:
            children.setdefault(parent, []).append(child)
        self.children = {p: tuple(sorted(c)) for p, c in children.items()}

    def _build_actors(self) -> list[_Actor]:
        rel: dict[tuple[str, str], list[str]] = {}
        for r in self.w.relations:
            rel.setdefault((r["relation_type"], r["source_id"]), []).append(r["target_id"])
        for tid in self.tools:
            self.tool_services[tid] = tuple(sorted(rel.get(("depends_on", tid), [])))
        out: list[_Actor] = []
        for a in sorted(self.w.agents, key=lambda d: d["id"]):
            aid = a["id"]
            out.append(
                _Actor(
                    agent_id=aid,
                    external_id=a["external_agent_id"],
                    domain_id=a["domain_id"],
                    model_id=sorted(rel[("uses_model", aid)])[0],
                    tool_ids=tuple(sorted(rel.get(("invokes", aid), []))),
                    service_ids=tuple(sorted(rel.get(("depends_on", aid), []))),
                    source_ids=tuple(
                        sorted(
                            set(rel.get(("grounded_by", aid), []))
                            | set(rel.get(("reads", aid), []))
                        )
                    )[:2],
                )
            )
        for u in self.w.undeclared_agents:
            out.append(
                _Actor(
                    agent_id=u.agent_id,
                    external_id=f"ext-{u.slug}",
                    domain_id=u.domain_id,
                    model_id=u.model_id,
                    tool_ids=tuple(sorted(u.tool_ids)),
                    service_ids=tuple(sorted(u.service_ids)),
                    source_ids=(),
                )
            )
        return out

    # ---- schedule --------------------------------------------------------------------
    def build(self) -> DemoTelemetry:
        for actor in self._actors:
            n = 0
            for day in range(self.w.days):
                day_start = self.epoch + day * DAY_MS
                for k in range(self.per_day):
                    rng = rng_for(self.seed, "demo-start", actor.agent_id, day, k)
                    start = day_start + int(rng.triangular(0, DAY_MS - 1000, 46_000_000))
                    if start >= self.base_start - _TRACE_TAIL_MS:
                        continue  # the last two hours are scripted
                    self._trace(actor, n, start, "day")
                    n += 1
            for phase, count, lo, hi in (
                ("baseline", self.baseline, self.base_start, self.inc_start),
                ("incident", self.incident, self.inc_start, self.end),
            ):
                for k in range(count):
                    rng = rng_for(self.seed, "demo-start", actor.agent_id, phase, k)
                    start = lo + 10_000 + int(rng.random() * (hi - lo - 10_000 - _TRACE_TAIL_MS))
                    self._trace(actor, n, start, phase)
                    n += 1
        self.events.sort(key=lambda e: (e["event_time"], e["event_id"]))
        self.costs.sort(key=lambda c: (c["recorded_at"], c["cost_id"]))
        return DemoTelemetry(
            self.events,
            self.costs,
            incident_manifest(self.w, self.seed),
        )

    # ---- one trace -------------------------------------------------------------------
    def _trace(self, actor: _Actor, n: int, start: int, phase: str) -> None:
        trace = digest_hex(f"{self.seed}:demo-tid:{actor.agent_id}:{n}", 16)
        ctx = _Trace(trace=trace, incident=phase == "incident")
        root = self._span(ctx, actor, "request", None, start, 0)
        end, outcome = self._run(ctx, actor, n, root["span_id"], start + 2, 0)
        root["duration_ms"] = end - start + 1
        root["outcome"] = outcome
        for ev in ctx.evs:
            self.events.append(
                TelemetryEvent.model_validate(ev).model_dump(mode="json", exclude_none=True)
            )

    def _span(
        self,
        ctx: _Trace,
        actor: _Actor,
        kind: str,
        parent: str | None,
        t: int,
        dur: int,
        outcome: str = "success",
        **extra: Any,
    ) -> Doc:
        ctx.seq += 1
        trace = ctx.trace
        ev: Doc = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"evt-{trace[:16]}-{ctx.seq:02d}",
            "event_time": fmt_ts(t),
            "cloud": self.w.cloud,
            "customer_id": self.w.customer,
            "domain_id": actor.domain_id,
            "source_id": "sandbox-gateway",
            "external_agent_id": actor.external_id,
            "canonical_agent_id": actor.agent_id,
            "request_id": "req-" + trace[:12],
            "trace_id": trace,
            "span_id": digest_hex(f"{trace}:{ctx.seq}", 8),
            "span_kind": kind,
            "environment": "sandbox",
            "outcome": outcome,
            "duration_ms": max(dur, 0),
            "sampling": {"rate": 1.0, "method": "none"},
        }
        if parent is not None:
            ev["parent_span_id"] = parent
        ev.update(extra)
        ctx.evs.append(ev)
        return ev

    def _run(
        self,
        ctx: _Trace,
        actor: _Actor,
        n: int,
        parent_span: str,
        start: int,
        depth: int,
        lineage: str = "",
    ) -> tuple[int, str]:
        """One agent_run (with its delegated children); returns (end time, outcome)."""
        w = self.w
        rng = rng_for(self.seed, "demo-trace", actor.agent_id, n, lineage)
        in_incident = ctx.incident and actor.agent_id in self.downstream
        outage = w.outage_service_id
        spec = self.models[actor.model_id]

        def span(
            kind: str, parent: str | None, t: int, dur: int, outcome: str = "success", **extra: Any
        ) -> Doc:
            return self._span(ctx, actor, kind, parent, t, dur, outcome, **extra)

        run = span("agent_run", parent_span, start, 0)
        run_id: str = run["span_id"]
        cur = start + 3
        failed = False

        for src in actor.source_ids:
            d = int(rng.uniform(30, 250))
            span("retrieval", run_id, cur, d, data_source_refs=[{"ref": src, "access": "read"}])
            cur += d

        for _ in range(1 + (rng.random() < 0.4)):
            tin = int(rng.lognormvariate(6.6, 0.6)) + 20
            tout = int(rng.lognormvariate(5.2, 0.6)) + 5
            d = max(
                1,
                int(
                    (spec.base_latency_ms + tout * spec.ms_per_output_token) * rng.uniform(0.8, 1.3)
                ),
            )
            call = span(
                "model_call",
                run_id,
                cur,
                d,
                provider=spec.provider,
                model=spec.model_name,
                model_version=spec.model_version,
                token_breakdown={"input": tin, "output": tout},
            )
            self._costs(actor, spec, call["event_id"], cur, cur + d, tin, tout)
            cur += d

        # Own RNG stream: the abandoned calls never shift the draws of the spans around them.
        arng = rng_for(self.seed, "demo-abandoned-call", actor.agent_id, n, lineage)

        def abandoned_call(t: int, failure: str) -> int:
            """The model call left waiting on a failed service result; returns its duration."""
            tin = int(arng.lognormvariate(6.6, 0.6)) + 20
            d = int(arng.uniform(8_000, 20_000) if failure == "timeout" else arng.uniform(150, 900))
            call = span(
                "model_call",
                run_id,
                t,
                d,
                failure,
                provider=spec.provider,
                model=spec.model_name,
                model_version=spec.model_version,
                token_breakdown={"input": tin, "output": 0},
            )
            self._costs(actor, spec, call["event_id"], t, t + d, tin, 0)
            return d

        def ride_out(t: int, failure: str, **identity: Any) -> tuple[int, str]:
            """After a failed outage call: abandon the model call, then retry the service call.

            Returns (time after the last span, final outcome). The agent gives up after
            ``INCIDENT_MAX_ATTEMPTS`` calls; a retry that gets through ends the loop.
            """
            attempts = 1
            while True:
                t += abandoned_call(t, failure)
                if attempts >= INCIDENT_MAX_ATTEMPTS:
                    return t, failure
                attempts += 1
                d, failure = self._outage_effect(arng, int(arng.uniform(20, 400)))
                span("tool_call", run_id, t, d, failure, **identity)
                t += d
                if failure == "success":
                    return t, failure

        bound_services: set[str] = set()
        for tid in actor.tool_ids:
            services = self.tool_services[tid]
            hits_outage = in_incident and outage in services
            if not (hits_outage or rng.random() < 0.6):
                continue
            tool = self.tools[tid]
            tool_ident: Doc = {
                "external_tool_id": "ext-" + _slug(tid),
                "canonical_tool_id": tid,
                "tool_name": tool["display_name"],
            }
            extra: Doc = {"tool": tool_ident}
            if services:
                extra["service"] = _service_identity(services[0])
                bound_services.update(services)
            if "mcp_server_ref" in tool:
                extra["mcp_server_ref"] = tool["mcp_server_ref"]
            d = int(rng.uniform(20, 400))
            outcome = "success"
            if hits_outage:
                d, outcome = self._outage_effect(rng, d)
            elif rng.random() < P_BACKGROUND_TOOL_ERROR:
                outcome = "error"
            span("tool_call", run_id, cur, d, outcome, **extra)
            cur += d
            if hits_outage and outcome != "success":
                cur, outcome = ride_out(cur, outcome, **extra)
                failed = failed or outcome != "success"

        for sid in actor.service_ids:
            if sid in bound_services:
                continue
            hits_outage = in_incident and sid == outage
            if not (hits_outage or rng.random() < 0.5):
                continue
            d = int(rng.uniform(40, 250))
            outcome = "success"
            if hits_outage:
                d, outcome = self._outage_effect(rng, d)
            elif rng.random() < P_BACKGROUND_TOOL_ERROR:
                outcome = "error"
            span("tool_call", run_id, cur, d, outcome, service=_service_identity(sid))
            cur += d
            if hits_outage and outcome != "success":
                cur, outcome = ride_out(cur, outcome, service=_service_identity(sid))
                failed = failed or outcome != "success"

        if depth < MAX_DELEGATION_DEPTH:
            # Own RNG stream: delegation never shifts the draws above. A child's failure does not
            # fail the parent, so the incident set is decided by the outage service alone.
            drng = rng_for(self.seed, "demo-deleg", actor.agent_id, n, lineage)
            for child_id in self.children.get(actor.agent_id, ()):
                if drng.random() >= P_DELEGATE:
                    continue
                deleg = span("delegation", run_id, cur, 0)
                end, child_outcome = self._run(
                    ctx,
                    self.actors[child_id],
                    n,
                    deleg["span_id"],
                    cur + 2,
                    depth + 1,
                    f"{lineage}/{actor.agent_id}",
                )
                deleg["duration_ms"] = end - cur + 1
                deleg["outcome"] = child_outcome
                cur = end + 1

        run_outcome = "success"
        if failed:
            span("error", run_id, cur, 2, "error")
            cur += 2
            run_outcome = "error"
        run["duration_ms"] = cur - start + 1
        run["outcome"] = run_outcome
        return cur + 1, run_outcome

    @staticmethod
    def _outage_effect(rng: random.Random, duration: int) -> tuple[int, str]:
        d = duration * INCIDENT_LATENCY_FACTOR
        if rng.random() < P_INCIDENT_FAIL:
            return d, "error" if rng.random() < 0.7 else "timeout"
        return d // 2, "success"

    def _costs(
        self, actor: _Actor, spec: ModelSpec, event_id: str, t0: int, t1: int, tin: int, tout: int
    ) -> None:
        w = self.w
        amount = price(spec, tin, tout, 0)
        base: Doc = {
            "schema_version": SCHEMA_VERSION,
            "currency": "USD",
            "cloud": w.cloud,
            "customer_id": w.customer,
            "domain_id": actor.domain_id,
            "canonical_agent_id": actor.agent_id,
            "provider": spec.provider,
            "model": spec.model_name,
            "model_version": spec.model_version,
            "retry_count": 0,
            "retry_amount": _money(Decimal(0)),
            "event_ids": [event_id],
            "dedupe_key": f"{w.customer}/{event_id}",
            "usage_start": fmt_ts(t0),
            "usage_end": fmt_ts(t1),
            "kind": "estimated",
            "amount": _money(amount),
            "allocation": {"compute": _money(amount)},
            "price_version": PRICE_VERSION,
            "price_effective_date": PRICE_EFFECTIVE_DATE,
        }
        for tag, source, view, offset in (
            ("gw", "sandbox-gateway", "gateway", 1000),
            ("app", "sandbox-application", "application", 2000),
        ):
            doc: Doc = {
                **base,
                "cost_id": f"cost-{tag}-{event_id}",
                "source_id": source,
                "observation_source": view,
                "token_breakdown": {"input": tin, "output": tout},
                "recorded_at": fmt_ts(t1 + offset),
            }
            self.costs.append(
                CostRecord.model_validate(doc).model_dump(mode="json", exclude_none=True)
            )


def _service_identity(canonical: str) -> Doc:
    return {"external_service_id": "ext-" + _slug(canonical), "canonical_service_id": canonical}


def build_demo_telemetry(
    world: DemoWorld,
    seed: int,
    *,
    traces_per_agent_day: int = DEFAULT_TRACES_PER_AGENT_DAY,
    baseline_traces: int = DEFAULT_BASELINE_TRACES,
    incident_traces: int = DEFAULT_INCIDENT_TRACES,
) -> DemoTelemetry:
    """Build telemetry and cost for all curated and telemetry-only agents, plus the manifest.

    Volume: each of the 36 agents gets ``traces_per_agent_day`` traces per day (minus the last
    two hours), ``baseline_traces`` in the hour before the incident and ``incident_traces`` in
    the incident hour. Every trace is about 5-9 spans.
    """
    return _Builder(world, seed, traces_per_agent_day, baseline_traces, incident_traces).build()


def incident_manifest(world: DemoWorld, seed: int) -> Doc:
    """The incident-manifest.json content: service, downstream agents, window, health shifts."""
    _, base_start, inc_start, end = _windows(world)
    service = next(s for s in world.services if s["id"] == world.outage_service_id)
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": "sandbox-incident-manifest",
        "seed": seed,
        "cloud": world.cloud,
        "epoch": world.epoch,
        "days": world.days,
        "service_id": world.outage_service_id,
        "service_name": service["display_name"],
        "downstream_agent_ids": list(world.downstream_agent_ids),
        "unrelated_agent_ids": list(world.unrelated_agent_ids),
        "undeclared_agent_ids": list(world.undeclared_agent_ids),
        "window": {"start": fmt_ts_s(inc_start), "end": fmt_ts_s(end)},
        "baseline_window": {"start": fmt_ts_s(base_start), "end": fmt_ts_s(inc_start)},
        "anchor": "last hour of the seeded window (epoch + days)",
        "effects": {
            "outcomes": ["error", "timeout"],
            "latency_factor": INCIDENT_LATENCY_FACTOR,
            "health_degraded_error_rate": HEALTH_DEGRADED_ERROR_RATE,
            "health_failing_error_rate": HEALTH_FAILING_ERROR_RATE,
        },
        "expected_health_transitions": [
            {
                "subject_kind": "agent",
                "subject_id": agent_id,
                "baseline_health": "ok",
                "incident_health": "failing",
            }
            for agent_id in world.downstream_agent_ids
        ],
    }


def write_demo_telemetry(telemetry: DemoTelemetry, out_dir: Path) -> dict[str, int]:
    """Write ``telemetry.ndjson`` and ``cost.ndjson`` in the generator layout; return counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, docs in (("telemetry.ndjson", telemetry.events), ("cost.ndjson", telemetry.costs)):
        with NdjsonWriter(out_dir / name) as writer:
            for doc in docs:
                writer.write_doc(doc)
            counts[name] = writer.count
    return counts


def write_incident_manifest(manifest: Doc, path: Path) -> None:
    write_json(path, manifest)
