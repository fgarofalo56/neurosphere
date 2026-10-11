"""World plan: the synthetic estate (domains, owners, agents, models, tools, sources, anomalies).

The plan is light (index-based dataclasses). Contract documents are produced lazily from it by
:mod:`sandbox.catalog` so memory stays bounded when the profile scales up.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from sandbox.config import (
    CATALOG_SOURCE,
    DOMAIN_NAMES,
    MODELS,
    ROLE_WORDS,
    SOURCE_KINDS,
    TOOL_KINDS,
    GenerateConfig,
    ModelSpec,
    parse_epoch,
)
from sandbox.ids import canonical_id, rng_for

DAY_MS = 86_400_000


@dataclass(slots=True)
class DomainPlan:
    idx: int
    slug: str
    name: str
    tools: list[int] = field(default_factory=list)
    sources: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ToolPlan:
    idx: int
    domain: int
    kind: str
    side_effects: str


@dataclass(slots=True)
class SourcePlan:
    idx: int
    domain: int  # -1 for estate-wide shared sources
    kind: str
    has_personal_data: bool


@dataclass(slots=True)
class AgentPlan:
    idx: int
    domain: int
    kind: str
    name: str
    parent: int | None
    children: list[int]
    declared_children: list[int]
    model: int
    tools: list[int]
    sources: list[int]
    extra_tool: int | None
    extra_source: int | None
    owner: int
    versions: int
    activity: float
    unused: bool = False


@dataclass(frozen=True, slots=True)
class Effect:
    """Behaviour multipliers applied to one agent over [start_day, end_day)."""

    start_day: int
    end_day: int
    token_mult: int = 1
    volume_mult: int = 1
    latency_mult: float = 1.0


@dataclass(slots=True)
class AnomalyPlan:
    seq: int
    type: str
    agents: list[int]
    start_day: int
    end_day: int
    details: dict[str, object]


@dataclass(slots=True)
class OwnerPlan:
    idx: int
    domain: int
    kind: str  # team | group | person | service_principal
    person: int | None


class World:
    def __init__(self, cfg: GenerateConfig) -> None:
        self.cfg = cfg
        self.seed = cfg.seed
        self.cloud = cfg.cloud
        self.customer = cfg.customer
        self.epoch_ms = parse_epoch(cfg.epoch)
        self.days = cfg.profile.days
        self.models: tuple[ModelSpec, ...] = MODELS
        self.domains: list[DomainPlan] = []
        self.tools: list[ToolPlan] = []
        self.sources: list[SourcePlan] = []
        self.owners: list[OwnerPlan] = []
        self.agents: list[AgentPlan] = []
        self.anomalies: list[AnomalyPlan] = []
        self.person_count = 0
        self.effects: dict[int, list[Effect]] = {}
        self._plan()

    # ---- IDs -------------------------------------------------------------------------
    def cid(self, type_: str, ident: str, source: str = CATALOG_SOURCE) -> str:
        return canonical_id(self.cloud, self.customer, source, type_, ident)

    def domain_id(self, i: int) -> str:
        return self.cid("domain", self.domains[i].slug)

    def agent_id(self, i: int) -> str:
        return self.cid("agent", f"a-{i:06d}")

    def agent_version_id(self, i: int, v: int) -> str:
        return self.cid("agent_version", f"a-{i:06d}-v{v}")

    def tool_id(self, i: int) -> str:
        return self.cid("tool", f"t-{i:05d}")

    def source_id(self, i: int) -> str:
        return self.cid("grounding_source", f"gs-{i:05d}")

    def model_id(self, i: int) -> str:
        return self.cid("model_deployment", self.models[i].slug)

    def owner_id(self, i: int) -> str:
        return self.cid("owner", f"o-{i:05d}")

    def end_ms(self) -> int:
        return self.epoch_ms + self.days * DAY_MS

    def effects_for(self, agent: int, day: int) -> tuple[int, int, float]:
        token, volume, latency = 1, 1, 1.0
        for e in self.effects.get(agent, ()):
            if e.start_day <= day < e.end_day:
                token *= e.token_mult
                volume *= e.volume_mult
                latency *= e.latency_mult
        return token, volume, latency

    # ---- planning --------------------------------------------------------------------
    def _plan(self) -> None:
        p = self.cfg.profile
        rng = rng_for(self.seed, "world")

        for d in range(p.domains):
            base = DOMAIN_NAMES[d % len(DOMAIN_NAMES)]
            name = base if d < len(DOMAIN_NAMES) else f"{base} {d // len(DOMAIN_NAMES) + 1}"
            self.domains.append(DomainPlan(d, f"dom-{d + 1:03d}", name))

        shared = [
            SourcePlan(0, -1, "knowledge_base", False),
            SourcePlan(1, -1, "search_index", False),
        ]
        self.sources.extend(shared)
        for dom in self.domains:
            for _ in range(p.tools_per_domain):
                t = ToolPlan(
                    len(self.tools),
                    dom.idx,
                    rng.choice(TOOL_KINDS),
                    rng.choice(("read_only", "read_only", "writes")),
                )
                self.tools.append(t)
                dom.tools.append(t.idx)
            for _ in range(p.sources_per_domain):
                s = SourcePlan(
                    len(self.sources),
                    dom.idx,
                    rng.choice(SOURCE_KINDS),
                    rng.random() < 0.15,
                )
                self.sources.append(s)
                dom.sources.append(s.idx)

        self.person_count = p.persons or max(6, p.agents // 10)
        for dom in self.domains:
            self.owners.append(OwnerPlan(len(self.owners), dom.idx, "team", None))
            if dom.idx % 2 == 0:
                self.owners.append(OwnerPlan(len(self.owners), dom.idx, "group", None))
        for n in range(self.person_count):
            dom = n % p.domains
            self.owners.append(OwnerPlan(len(self.owners), dom, "person", n))
        self.owners.append(OwnerPlan(len(self.owners), 0, "service_principal", None))

        owners_by_domain: dict[int, list[int]] = {}
        for o in self.owners:
            owners_by_domain.setdefault(o.domain, []).append(o.idx)

        chat_models = [i for i, m in enumerate(self.models) if "embedding" not in m.modalities]
        n_sub = int(p.agents * p.subagent_fraction)
        n_parent = p.agents - n_sub
        for i in range(p.agents):
            is_sub = i >= n_parent
            if is_sub:
                parent = rng.randrange(n_parent)
                while len(self.agents[parent].children) >= 3:
                    parent = rng.randrange(n_parent)
                dom = self.agents[parent].domain
                kind = "sub_agent"
            else:
                parent = None
                dom = rng.randrange(p.domains)
                kind = rng.choice(("assistant", "assistant", "workflow", "autonomous"))
            d = self.domains[dom]
            tools = rng.sample(d.tools, rng.randint(1, min(3, len(d.tools))))
            n_src = rng.randint(0, min(2, len(d.sources)))
            sources = rng.sample(d.sources, n_src)
            if rng.random() < 0.1:
                sources.append(rng.choice((0, 1)))
            leftover_t = [t for t in d.tools if t not in tools]
            leftover_s = [s for s in d.sources if s not in sources]
            extra_tool = rng.choice(leftover_t) if leftover_t and rng.random() < 0.25 else None
            extra_source = rng.choice(leftover_s) if leftover_s and rng.random() < 0.2 else None
            name = f"{d.name} {rng.choice(ROLE_WORDS)} {i + 1:04d}"
            agent = AgentPlan(
                idx=i,
                domain=dom,
                kind=kind,
                name=name,
                parent=parent,
                children=[],
                declared_children=[],
                model=rng.choice(chat_models),
                tools=tools,
                sources=sorted(set(sources)),
                extra_tool=extra_tool,
                extra_source=extra_source,
                owner=rng.choice(owners_by_domain.get(dom, [0])),
                versions=rng.randint(1, 3),
                activity=0.3 + rng.random() * 2.2,
            )
            self.agents.append(agent)
            if parent is not None:
                self.agents[parent].children.append(i)
        for a in self.agents:
            for c in a.children:
                # about two thirds of delegations are declared; the rest are only observable
                # in traces and become inferred relations
                if rng_for(self.seed, "decl", a.idx, c).random() < 0.67:
                    a.declared_children.append(c)

        self._plan_anomalies(rng_for(self.seed, "anomalies"))

    def _plan_anomalies(self, rng: random.Random) -> None:
        p = self.cfg.profile
        parents = [a.idx for a in self.agents if a.parent is None]
        solo = [i for i in parents if not self.agents[i].children]
        rng.shuffle(parents)
        rng.shuffle(solo)
        used: set[int] = set()

        def take(pool: list[int]) -> int:
            for i in pool:
                if i not in used:
                    used.add(i)
                    return i
            raise ValueError("not enough eligible agents for the requested anomalies")

        seq = 0
        days = self.days
        spike_day = max(1, days // 2)
        spike_len = 1 if days < 7 else 2
        for _ in range(p.cost_spikes):
            seq += 1
            a = take(parents)
            mult = 12
            self.effects.setdefault(a, []).append(
                Effect(spike_day, spike_day + spike_len, token_mult=mult, volume_mult=3)
            )
            self.anomalies.append(
                AnomalyPlan(
                    seq,
                    "cost_spike",
                    [a],
                    spike_day,
                    spike_day + spike_len,
                    {"token_multiplier": mult, "volume_multiplier": 3},
                )
            )
        for _ in range(p.latency_regressions):
            seq += 1
            a = take(parents)
            start = max(1, days // 2)
            mult = 3.0
            self.effects.setdefault(a, []).append(Effect(start, days, latency_mult=mult))
            self.anomalies.append(
                AnomalyPlan(
                    seq, "latency_regression", [a], start, days, {"latency_multiplier": mult}
                )
            )
        for _ in range(p.unused_agents):
            seq += 1
            a = take(solo)
            self.agents[a].unused = True
            self.anomalies.append(
                AnomalyPlan(
                    seq,
                    "unused_agent",
                    [a],
                    0,
                    days,
                    {"observed_trace_count": 0, "lifecycle_status": "active"},
                )
            )
        for _ in range(p.duplicate_pairs):
            seq += 1
            a = take(solo)
            b = take(solo)
            src, dup = self.agents[a], self.agents[b]
            dup.domain = src.domain
            dup.model = src.model
            dup.kind = src.kind
            dup.owner = src.owner
            dom_sources = self.domains[src.domain].sources
            while len(src.sources) < 2:
                src.sources = sorted({*src.sources, *dom_sources[: 2 - len(src.sources) + 1]})
            dup.sources = list(src.sources)
            dup.tools = list(src.tools)
            shared = [self.source_id(s) for s in src.sources]
            self.anomalies.append(
                AnomalyPlan(
                    seq,
                    "duplicate_agent_candidates",
                    [a, b],
                    0,
                    days,
                    {
                        "label": "candidate",
                        "auto_merge": False,
                        "review": "consolidation_review_only",
                        "basis": ["shared_grounding_sources", "same_model_deployment"],
                        "shared_grounding_source_ids": shared,
                        "model_deployment_id": self.model_id(src.model),
                    },
                )
            )
