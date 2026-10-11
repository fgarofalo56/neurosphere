"""Delegation traces as TelemetryEvent spans, plus the cost observations they imply.

One trace = request -> agent_run -> (retrieval | model_call [+ retry] | tool_call |
delegation -> child agent_run)*, with seeded retries, errors and cancellations. Each trace
draws from its own RNG stream keyed on (seed, agent, day, index), so output does not depend
on generation order and the first trace of an agent is a pure function of the seed (the
catalog cites it as evidence for inferred relations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neurosphere_contracts.telemetry.v1 import telemetry_event

from sandbox.config import SCHEMA_VERSION
from sandbox.costs import cost_views
from sandbox.ids import digest_hex, fmt_ts, rng_for
from sandbox.world import AgentPlan, World

Doc = dict[str, Any]

P_RETRY = 0.06
P_CANCEL = 0.012
P_RUN_ERROR = 0.02
P_TOOL_ERROR = 0.03
MAX_DEPTH = 3


def trace_hex(seed: int, agent: int, day: int, k: int) -> str:
    return digest_hex(f"{seed}:tid:{agent}:{day}:{k}", 16)


@dataclass(slots=True)
class _Ctx:
    trace: str
    request_id: str
    day: int
    rng: Any
    seq: int = 0
    events: list[Doc] = field(default_factory=list)
    costs: list[Doc] = field(default_factory=list)


class TraceGenerator:
    def __init__(self, world: World) -> None:
        self.world = world

    def trace_count(self, agent: int, day: int) -> int:
        a = self.world.agents[agent]
        if a.unused or a.parent is not None:
            return 0  # sub-agents are only exercised through delegation from their parent
        _, volume, _ = self.world.effects_for(agent, day)
        rng = rng_for(self.world.seed, "vol", agent, day)
        mean = self.world.cfg.profile.traces_per_agent_day * a.activity * volume
        whole = int(mean)
        return whole + (1 if rng.random() < mean - whole else 0)

    def start_offset_ms(self, agent: int, day: int, k: int) -> int:
        rng = rng_for(self.world.seed, "start", agent, day, k)
        return int(rng.triangular(0, 86_399_000, 46_000_000))

    # ---- one trace -------------------------------------------------------------------
    def build(
        self, agent: int, day: int, k: int, start_ms: int
    ) -> tuple[list[tuple[int, str, Doc]], list[Doc]]:
        w = self.world
        trace = trace_hex(w.seed, agent, day, k)
        ctx = _Ctx(trace, "req-" + trace[:12], day, rng_for(w.seed, "trace", agent, day, k))
        forced = day == 0 and k == 0
        root = self._span(ctx, agent, "request", None, start_ms, 0)
        end, outcome = self._run(ctx, w.agents[agent], root["span_id"], start_ms + 2, forced, 0)
        root["duration_ms"] = end - start_ms + 1
        root["outcome"] = outcome
        stamped: list[tuple[int, str, Doc]] = []
        for ev in ctx.events:
            t = ev.pop("_t")
            doc = telemetry_event.TelemetryEvent.model_validate(ev).model_dump(
                mode="json", exclude_none=True
            )
            stamped.append((t, doc["event_id"], doc))
        return stamped, ctx.costs

    def _span(
        self,
        ctx: _Ctx,
        agent: int,
        kind: str,
        parent: str | None,
        t: int,
        duration: int,
        outcome: str = "success",
        **extra: Any,
    ) -> Doc:
        w = self.world
        ctx.seq += 1
        a = w.agents[agent]
        ev: Doc = {
            "_t": t,
            "schema_version": SCHEMA_VERSION,
            "event_id": f"evt-{ctx.trace[:16]}-{ctx.seq:02d}",
            "event_time": fmt_ts(t),
            "cloud": w.cloud,
            "customer_id": w.customer,
            "domain_id": w.domain_id(a.domain),
            "source_id": "sandbox-gateway",
            "external_agent_id": f"ext-a-{agent:06d}",
            "canonical_agent_id": w.agent_id(agent),
            "request_id": ctx.request_id,
            "trace_id": ctx.trace,
            "span_id": digest_hex(f"{ctx.trace}:{ctx.seq}", 8),
            "span_kind": kind,
            "environment": "sandbox",
            "outcome": outcome,
            "duration_ms": max(duration, 0),
            "sampling": {"rate": 1.0, "method": "none"},
        }
        if parent is not None:
            ev["parent_span_id"] = parent
        ev.update(extra)
        ctx.events.append(ev)
        return ev

    def _run(
        self, ctx: _Ctx, a: AgentPlan, parent: str, t: int, forced: bool, depth: int
    ) -> tuple[int, str]:
        w = self.world
        rng = ctx.rng
        tok_mult, _, lat = w.effects_for(a.idx, ctx.day)
        run = self._span(ctx, a.idx, "agent_run", parent, t, 0)
        run_id: str = run["span_id"]
        cur = t + 3
        outcome = "success"

        sources = list(a.sources)
        if a.extra_source is not None and (forced or rng.random() < 0.3):
            sources.append(a.extra_source)
        for s in sources:
            d = max(1, int(rng.uniform(30, 300) * lat))
            self._span(
                ctx,
                a.idx,
                "retrieval",
                run_id,
                cur,
                d,
                data_source_refs=[{"ref": w.source_id(s), "access": "read"}],
            )
            cur += d

        spec = w.models[a.model]
        calls = 1 + (rng.random() < 0.4) + (rng.random() < 0.15)
        for _ in range(calls):
            tin = int(rng.lognormvariate(6.6, 0.7)) * tok_mult + 20
            tout = int(rng.lognormvariate(5.4, 0.7)) * tok_mult + 5
            cached = int(tin * rng.random() * 0.5) if rng.random() < 0.3 else 0
            retries = 0
            retry_in = 0
            call_start = cur
            if rng.random() < P_RETRY:
                fail_d = max(1, int(spec.base_latency_ms * rng.uniform(0.5, 2.0) * lat))
                self._span(
                    ctx,
                    a.idx,
                    "model_call",
                    run_id,
                    cur,
                    fail_d,
                    rng.choice(("error", "timeout")),
                    provider=spec.provider,
                    model=spec.model_name,
                    model_version=spec.model_version,
                    token_breakdown={"input": tin, "output": 0},
                )
                cur += fail_d
                self._span(ctx, a.idx, "retry", run_id, cur, 250, retry_attempt=1)
                cur += 250
                retries, retry_in = 1, tin
            d = max(
                1,
                int(
                    (spec.base_latency_ms + tout * spec.ms_per_output_token)
                    * rng.uniform(0.8, 1.3)
                    * lat
                ),
            )
            call = self._span(
                ctx,
                a.idx,
                "model_call",
                run_id,
                cur,
                d,
                provider=spec.provider,
                model=spec.model_name,
                model_version=spec.model_version,
                token_breakdown={"input": tin, "output": tout, "cached": cached},
            )
            cur += d
            ctx.costs.extend(
                cost_views(
                    w,
                    rng,
                    agent_idx=a.idx,
                    spec=spec,
                    tokens=(tin, tout, cached),
                    event_id=call["event_id"],
                    start_ms=call_start,
                    end_ms=cur,
                    retry_count=retries,
                    retry_input_tokens=retry_in,
                )
            )

        roll = rng.random()
        if roll < P_CANCEL:
            self._span(ctx, a.idx, "cancellation", run_id, cur, 5, "cancelled")
            cur += 5
            outcome = "cancelled"
        elif roll < P_CANCEL + P_RUN_ERROR:
            self._span(ctx, a.idx, "error", run_id, cur, 2, "error")
            cur += 2
            outcome = "error"
        else:
            tools = list(a.tools)
            if a.extra_tool is not None:
                tools.append(a.extra_tool)
            for ti in tools:
                if not (forced or rng.random() < 0.5):
                    continue
                d = max(1, int(rng.uniform(20, 600) * lat))
                writes = w.tools[ti].side_effects == "writes"
                failed = rng.random() < P_TOOL_ERROR
                self._span(
                    ctx,
                    a.idx,
                    "tool_call",
                    run_id,
                    cur,
                    d,
                    "error" if failed else "success",
                    data_source_refs=[
                        {"ref": w.tool_id(ti), "access": "write" if writes else "read"}
                    ],
                )
                cur += d
            if depth < MAX_DEPTH:
                for c in a.children:
                    p = 0.5 if c in a.declared_children else 0.3
                    if not (forced or rng.random() < p):
                        continue
                    deleg = self._span(ctx, a.idx, "delegation", run_id, cur, 0)
                    end, child_out = self._run(
                        ctx, w.agents[c], deleg["span_id"], cur + 2, False, depth + 1
                    )
                    deleg["duration_ms"] = end - cur + 1
                    deleg["outcome"] = child_out
                    cur = end + 1
        run["duration_ms"] = cur - t + 2
        run["outcome"] = outcome
        return cur + 1, outcome
