"""Duplicate-candidate similarity over PRESENTED catalog relations (PRP-15 item 2, delta D2).

Read-only by construction: the job talks to the catalog through ``GraphQuery.neighbors``
(``view="presented"`` only, so locked and curated relations shape what it sees and hidden
edges are invisible) and one scope-filtered agent listing. It owns no write path, and a
static test (``test_no_merge_paths``) keeps it that way.

Decisions
---------
* Scope: only agents of the caller's customer, cloud and allowed domains are listed and read.
  Targets outside the scope are cut by ``GraphQuery`` (fail closed); their signal is simply
  unobserved.
* Same domain is a GATE: a pair is formed only within one domain. Cross-domain overlap of
  sources or models is expected (shared estate assets) and says little about redundancy,
  and it keeps every record inside a single ``domain_id`` for authorization.
* Signals: confidence-weighted Jaccard overlap of presented relation targets for
  ``grounded_by`` sources, ``uses_model`` deployments, ``invokes`` tools and ``owned_by``
  owners; equality of ``agent_kind``; plus an optional pluggable provider (embeddings).
  Trace-inferred relations count at ``inferred_edge_weight`` of their confidence.
* ``similarity = sum(w_i * s_i) / sum(w_i)`` over the OBSERVED signals (both agents have a
  relation of that type, target inside the scope). Unobserved is unknown, not a mismatch.
* Uncertainty (``rule_bound``), derived from the evidence rather than a distribution:
  ``lower`` discounts every observed signal by the lowest confidence among the presented
  edges that support it; ``upper`` adds the total weight share of unobserved signals (they
  could still overlap); ``score`` sits between.
* ``review_floor <= similarity < min_similarity`` pairs go to ``review_candidates`` and are
  NOT recommendations.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.recommendations.v1.recommendation import (
    Recommendation,
    TimeRange,
)
from neurosphere_core.catalog.protocol import (
    EdgeFilter,
    EntityFilter,
    GraphQuery,
    NeighborsRequest,
    PresentedEdge,
)
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.duplicates.config import DuplicateConfig
from neurosphere_workers.recommendations.duplicates.models import (
    AgentLister,
    DuplicateCandidate,
    DuplicateRun,
    ReviewCandidate,
    SignalBreakdown,
    SimilaritySignalProvider,
)

SCHEMA_VERSION = "1.0.0"
PAGE = 500
MAX_EVIDENCE_IDS = 200
RELATION_TYPES: list[Literal["grounded_by", "uses_model", "invokes", "owned_by"]] = [
    "grounded_by",
    "uses_model",
    "invokes",
    "owned_by",
]
_LIFECYCLE: list[Literal["draft", "active", "deprecated"]] = ["draft", "active", "deprecated"]


@dataclass(frozen=True, slots=True)
class _Link:
    edge_id: str
    confidence: float


@dataclass(slots=True)
class _Profile:
    agent_id: str
    domain_id: str
    agent_kind: str = ""
    sources: dict[str, _Link] = field(default_factory=dict)
    models: dict[str, _Link] = field(default_factory=dict)
    tools: dict[str, _Link] = field(default_factory=dict)
    owners: dict[str, _Link] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Signal:
    name: str
    weight: float
    observed: bool
    value: float
    confidence: float
    shared: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Scored:
    a: _Profile
    b: _Profile
    similarity: float
    lower: float
    upper: float
    observed_weight: float
    total_weight: float
    signals: tuple[_Signal, ...]
    breakdown: SignalBreakdown


def _text(value: Any) -> str:
    """Contract scalars are plain strings or single-field root models; return the string."""
    return str(getattr(value, "root", value))


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _valid_in(edge: PresentedEdge, window: TimeRange) -> bool:
    """False when the edge's validity interval does not intersect the observation window."""
    start, end = _parse(window.start.root), _parse(window.end.root)
    if _parse(edge.validity.valid_from.root) >= end:
        return False
    valid_to = edge.validity.valid_to
    return valid_to is None or _parse(valid_to.root) > start


def _jaccard(a: dict[str, _Link], b: dict[str, _Link]) -> float:
    """Confidence-weighted Jaccard over presented relation targets.

    ``sum(min(ca, cb)) / sum(max(ca, cb))`` with confidence 0 for a missing target, so a
    declared relation (confidence 1.0) counts fully and a low-confidence inferred one counts
    in proportion. With all confidences 1.0 this is the plain Jaccard index.
    """
    low = high = 0.0
    for target in a.keys() | b.keys():
        ca = a[target].confidence if target in a else 0.0
        cb = b[target].confidence if target in b else 0.0
        low += min(ca, cb)
        high += max(ca, cb)
    return low / high if high > 0.0 else 0.0


class DuplicateDetector:
    """Compute consolidation-review candidates. Holds read handles only."""

    def __init__(
        self,
        graph: GraphQuery,
        agents: AgentLister,
        config: DuplicateConfig | None = None,
        *,
        signal_provider: SimilaritySignalProvider | None = None,
    ) -> None:
        self._graph = graph
        self._agents = agents
        self._config = config or DuplicateConfig()
        self._provider = signal_provider

    @property
    def config(self) -> DuplicateConfig:
        return self._config

    async def run(
        self,
        *,
        scope: IdentityScope,
        window: TimeRange,
        created_at: str,
    ) -> DuplicateRun:
        """One bounded pass. ``window`` is the catalog observation window; ``created_at`` is
        supplied by the caller (this module never reads the wall clock)."""
        cfg = self._config
        reasons: list[str] = []
        profiles, listing_truncated = await self._load_profiles(scope, window, reasons)
        if listing_truncated:
            reasons.append("max_agents")

        scored: list[_Scored] = []
        compared = 0
        pair_cap_hit = False
        for a, b in self._pairs(profiles):
            if compared >= cfg.max_pairs_compared:
                pair_cap_hit = True
                break
            compared += 1
            result = self._score(a, b)
            if result.breakdown.corroborating_signals < cfg.min_corroborating_signals:
                continue
            if len(result.breakdown.shared_source_ids) < cfg.min_shared_sources:
                continue
            if result.observed_weight < cfg.min_observed_fraction * result.total_weight:
                continue
            if result.similarity >= cfg.review_floor:
                scored.append(result)
        if pair_cap_hit:
            reasons.append("max_pairs_compared")

        scored.sort(key=lambda s: (-s.similarity, s.a.agent_id, s.b.agent_id))
        strong = [s for s in scored if s.similarity >= cfg.min_similarity]
        weak = [s for s in scored if s.similarity < cfg.min_similarity]
        if len(strong) > cfg.max_candidates or len(weak) > cfg.max_candidates:
            reasons.append("max_candidates")
        strong, weak = strong[: cfg.max_candidates], weak[: cfg.max_candidates]

        owner_cache = {p.agent_id: p for p in profiles}
        candidates = tuple(
            DuplicateCandidate(
                recommendation=self._record(s, scope, window, created_at, owner_cache),
                breakdown=s.breakdown,
            )
            for s in strong
        )
        review = tuple(
            ReviewCandidate(
                subject_ids=(s.a.agent_id, s.b.agent_id),
                domain_id=s.a.domain_id,
                similarity=s.similarity,
                breakdown=s.breakdown,
            )
            for s in weak
        )
        unique = tuple(dict.fromkeys(reasons))
        return DuplicateRun(
            candidates=candidates,
            review_candidates=review,
            truncated=bool(unique),
            truncation_reasons=unique,
            agents_considered=len(profiles),
            pairs_compared=compared,
            generator_id=cfg.generator_id,
            generator_version=cfg.version,
        )

    # ------------------------------------------------------------------ reading

    async def _load_profiles(
        self, scope: IdentityScope, window: TimeRange, reasons: list[str]
    ) -> tuple[list[_Profile], bool]:
        cfg = self._config
        allowed = list(scope.allowed_domains)
        if not allowed:
            return [], False
        flt = EntityFilter(
            entity_types=["agent"], domain_ids=allowed, lifecycle_statuses=list(_LIFECYCLE)
        )
        profiles: list[_Profile] = []
        cursor: str | None = None
        truncated = False
        while True:
            page = await self._agents.list_entities(
                scope, flt, PageRequest(page_size=PAGE, cursor=cursor)
            )
            for entity in page.items:
                agent_id = _text(getattr(entity, "id", ""))
                domain_id = _text(getattr(entity, "domain_id", ""))
                # Defence in depth: the listing is already scope-filtered.
                if (
                    getattr(entity, "entity_type", None) != "agent"
                    or domain_id not in allowed
                    or _text(getattr(entity, "customer_id", "")) != scope.customer_id
                    or _text(getattr(entity, "cloud", "")) != scope.cloud
                ):
                    continue
                if len(profiles) >= cfg.max_agents:
                    truncated = True
                    break
                profile = await self._profile(scope, agent_id, domain_id, window, reasons)
                profile.agent_kind = _text(getattr(entity, "agent_kind", ""))
                profiles.append(profile)
            if truncated or page.next_cursor is None:
                break
            cursor = page.next_cursor
        profiles.sort(key=lambda p: p.agent_id)
        return profiles, truncated

    async def _profile(
        self,
        scope: IdentityScope,
        agent_id: str,
        domain_id: str,
        window: TimeRange,
        reasons: list[str],
    ) -> _Profile:
        cfg = self._config
        request = NeighborsRequest(
            node_id=agent_id,
            direction="out",
            filters=EdgeFilter(relation_types=list(RELATION_TYPES)),
            budget=Budget(
                timeout_ms=cfg.neighbor_timeout_ms, limit=cfg.max_edges_per_agent, max_depth=1
            ),
            view="presented",
        )
        result = await self._graph.neighbors(scope, request)
        if result.truncated:
            reasons.append("max_edges_per_agent")
        profile = _Profile(agent_id=agent_id, domain_id=domain_id)
        by_type = {
            "grounded_by": profile.sources,
            "uses_model": profile.models,
            "invokes": profile.tools,
            "owned_by": profile.owners,
        }
        for edge in sorted(result.edges, key=lambda e: e.edge_id):
            bucket = by_type.get(edge.relation_type)
            if bucket is None or edge.hidden or edge.source_id != agent_id:
                continue
            if not _valid_in(edge, window):
                continue
            weight = float(edge.confidence)
            if edge.status == "inferred":
                weight *= cfg.inferred_edge_weight
            if weight > 0.0:
                bucket.setdefault(edge.target_id, _Link(edge.edge_id, weight))
        return profile

    # ------------------------------------------------------------------ pairing

    def _pairs(self, profiles: Sequence[_Profile]) -> Iterator[tuple[_Profile, _Profile]]:
        """Deterministic in-domain pairs (a < b). Relation-based pairs need a shared target;
        with a signal provider every in-domain pair is a candidate."""
        by_domain: dict[str, list[_Profile]] = defaultdict(list)
        for p in profiles:
            by_domain[p.domain_id].append(p)
        for domain in sorted(by_domain):
            members = by_domain[domain]
            if self._provider is not None:
                for i, a in enumerate(members):
                    for b in members[i + 1 :]:
                        yield a, b
                continue
            index: dict[tuple[str, str], list[int]] = defaultdict(list)
            for i, p in enumerate(members):
                for kind, links in (("s", p.sources), ("m", p.models), ("t", p.tools)):
                    for target in links:
                        index[(kind, target)].append(i)
            for i, a in enumerate(members):
                partners: set[int] = set()
                for kind, links in (("s", a.sources), ("m", a.models), ("t", a.tools)):
                    for target in links:
                        partners |= {j for j in index[(kind, target)] if j > i}
                for j in sorted(partners):
                    yield a, members[j]

    # ------------------------------------------------------------------ scoring

    def _signal(
        self,
        name: str,
        weight: float,
        a: dict[str, _Link],
        b: dict[str, _Link],
    ) -> _Signal:
        observed = bool(a) and bool(b)
        shared = sorted(a.keys() & b.keys())
        value = _jaccard(a, b) if observed else 0.0
        links = [a[t] for t in shared] + [b[t] for t in shared]
        confidence = min((link.confidence for link in links), default=1.0)
        evidence = tuple(sorted({link.edge_id for link in links}))
        return _Signal(name, weight, observed, value, confidence, tuple(shared), evidence)

    @staticmethod
    def _kind_signal(weight: float, a: _Profile, b: _Profile) -> _Signal:
        """Same ``agent_kind`` (assistant, workflow, ...). An attribute, not a relation, so it
        cites no edge evidence and never counts as a corroborating signal on its own."""
        observed = bool(a.agent_kind) and bool(b.agent_kind)
        value = 1.0 if observed and a.agent_kind == b.agent_kind else 0.0
        return _Signal("agent_kind", weight, observed, value, 1.0, (), ())

    def _score(self, a: _Profile, b: _Profile) -> _Scored:
        w = self._config.weights
        signals = [
            self._signal("grounding_sources", w.grounding_sources, a.sources, b.sources),
            self._signal("model_deployment", w.model_deployment, a.models, b.models),
            self._signal("tools", w.tools, a.tools, b.tools),
            self._signal("owner", w.owner, a.owners, b.owners),
            self._kind_signal(w.agent_kind, a, b),
        ]
        embedding: float | None = None
        if self._provider is not None:
            raw = self._provider.similarity(a.agent_id, b.agent_id)
            if raw is not None:
                embedding = min(1.0, max(0.0, float(raw)))
            signals.append(
                _Signal(
                    "embedding",
                    w.embedding,
                    embedding is not None,
                    embedding or 0.0,
                    1.0,
                    (),
                    (),
                )
            )
        total = sum(s.weight for s in signals)
        observed_weight = sum(s.weight for s in signals if s.observed)
        # Score over the OBSERVED signals only: an unobserved signal (a side has no relation of
        # that type, or its target is outside the caller's scope) is unknown, not a mismatch.
        # The weight share it holds widens ``upper`` instead (O >= N makes upper >= score).
        if observed_weight > 0.0:
            score = sum(s.weight * s.value for s in signals if s.observed) / observed_weight
            lower = (
                sum(s.weight * s.value * s.confidence for s in signals if s.observed)
                / observed_weight
            )
        else:
            score = lower = 0.0
        unobserved_share = (total - observed_weight) / total if total > 0.0 else 1.0
        upper = min(1.0, max(score, (score * observed_weight) / total + unobserved_share))
        by_name = {s.name: s for s in signals}
        breakdown = SignalBreakdown(
            shared_source_ids=by_name["grounding_sources"].shared,
            shared_model_deployment_ids=by_name["model_deployment"].shared,
            shared_tool_ids=by_name["tools"].shared,
            grounding_sources=round(by_name["grounding_sources"].value, 6),
            model_deployment=round(by_name["model_deployment"].value, 6),
            tools=round(by_name["tools"].value, 6),
            shared_owner_ids=by_name["owner"].shared,
            owner=round(by_name["owner"].value, 6),
            agent_kind=round(by_name["agent_kind"].value, 6),
            embedding=None if embedding is None else round(embedding, 6),
            same_domain_id=a.domain_id,
            unobserved_signals=tuple(s.name for s in signals if not s.observed),
            corroborating_signals=sum(
                1 for s in signals if s.value > 0.0 and s.name != "agent_kind"
            ),
        )
        return _Scored(
            a=a,
            b=b,
            similarity=round(score, 6),
            lower=round(lower, 6),
            upper=round(upper, 6),
            observed_weight=observed_weight,
            total_weight=total,
            signals=tuple(signals),
            breakdown=breakdown,
        )

    # ------------------------------------------------------------------ record

    def _recommendation_id(
        self, scope: IdentityScope, subjects: Sequence[str], window: TimeRange
    ) -> str:
        cfg = self._config
        basis = "|".join(
            [cfg.generator_id, cfg.version, *sorted(subjects), window.start.root, window.end.root]
        )
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
        # Canonical-ID id segments allow no underscore, so the kind is hyphenated.
        prefix = f"{scope.cloud}:{scope.customer_id}:neurosphere:recommendation"
        return f"{prefix}:candidate-duplicate-{digest}"

    def _record(
        self,
        s: _Scored,
        scope: IdentityScope,
        window: TimeRange,
        created_at: str,
        profiles: dict[str, _Profile],
    ) -> Recommendation:
        cfg = self._config
        subjects = sorted([s.a.agent_id, s.b.agent_id])
        evidence = sorted({e for sig in s.signals for e in sig.evidence})[:MAX_EVIDENCE_IDS]
        owner_id, resolution = self._owner(profiles[subjects[0]], profiles[subjects[1]])
        fraction = s.observed_weight / s.total_weight
        owner_known = owner_id is not None
        document = {
            "schema_version": SCHEMA_VERSION,
            "recommendation_id": self._recommendation_id(scope, subjects, window),
            "cloud": scope.cloud,
            "customer_id": scope.customer_id,
            "domain_id": s.a.domain_id,
            "kind": "candidate_duplicate",
            "subject_ids": subjects,
            "method": "statistical",
            "generator": {"generator_id": cfg.generator_id, "generator_version": cfg.version},
            "evidence_status": "sufficient",
            "score": s.similarity,
            "evidence_window": {"start": window.start.root, "end": window.end.root},
            "evidence_ids": evidence,
            "coverage": {
                "method": "full" if fraction >= 1.0 else "partial",
                "observed_fraction": round(fraction, 6),
            },
            "uncertainty": {"method": "rule_bound", "lower": s.lower, "upper": s.upper},
            "prerequisites": [
                {"kind": "owner_consent", "status": "unmet" if owner_known else "unknown"},
                {"kind": "approval", "status": "unmet"},
            ],
            "owner": {"resolution": resolution, "owner_id": owner_id},
            "advisory": True,
            "created_at": created_at,
        }
        return Recommendation.model_validate(cast("dict[str, Any]", document))

    @staticmethod
    def _owner(
        first: _Profile, second: _Profile
    ) -> tuple[str | None, Literal["assigned", "inferred", "unresolved"]]:
        """Both agents owned by the same owner -> assigned; otherwise the first (sorted)
        agent's owner, marked inferred; no ``owned_by`` -> unresolved with a null owner."""
        a, b = sorted(first.owners), sorted(second.owners)
        if a and a == b:
            return a[0], "assigned"
        for owners in (a, b):
            if owners:
                return owners[0], "inferred"
        return None, "unresolved"
