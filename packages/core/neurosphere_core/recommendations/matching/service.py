"""The agent/tool matcher service (PRP-72 item 3).

One call is a fixed pipeline with a bounded number of backend calls: ONE ``AuthorizedSearch``
request (scope is applied before ranking, so out-of-scope documents never appear and never
influence a score or a ``matched`` count), one scoped re-fetch per candidate, at most ONE
aggregate read per candidate domain (at most ``MAX_TELEMETRY_DOMAINS`` domains), at most ONE
bounded ``neighbors`` walk per context entity, ONE ``list_feedback`` read and ONE
``record_match`` write.

Honesty rules: an unknown value is ``None`` and carries a reason code, never 0; a failed or
missing telemetry reader degrades telemetry to unobserved instead of failing the call; a budget
that stopped work sets ``truncated`` and ``partial_reason``. Task text is only ever tokenized:
it is never stored, logged or returned, and neither are tokens or principal identifiers logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.recommendations.v1.agent_match_feedback_request import (
    AgentMatchFeedbackRequest,
)
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import (
    AgentMatchResponse,
    AgentMatchSignal,
)

from neurosphere_core.aggregates.models import AggregateWindow, SubjectPoint, bucket_start
from neurosphere_core.aggregates.subject import (
    MAX_SUBJECT_KEYS_PER_READ,
    SubjectMetricsReader,
    subject_series_key,
)
from neurosphere_core.catalog.protocol import CatalogEntity, GraphQuery, NeighborsRequest
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import (
    AuthorizedSearch,
    SearchFilters,
    SearchRequest,
)

from .combine import combine, rank_candidates
from .feedback import (
    FeedbackMetrics,
    FeedbackRecord,
    FeedbackStore,
    MatchCandidateRecord,
    MatchRecord,
    feedback_signal,
)
from .models import CombinedResult, ProximityPath, SignalValue
from .settings import SIGNAL_NAMES, MatchSettings
from .signals import (
    latency_pool_median,
    lexical_signal,
    proximity_signal,
    tag_signal,
    telemetry_signal,
)
from .tokens import normalize_tokens

__all__ = [
    "MAX_TELEMETRY_DOMAINS",
    "RANKER_ID",
    "RANKER_VERSION",
    "AgentMatchReader",
    "AgentMatcher",
    "MatchResult",
]

_log = logging.getLogger(__name__)

MAX_TELEMETRY_DOMAINS: Final = 20
RANKER_ID: Final = "weighted-signals"
RANKER_VERSION: Final = "1.0.0"
_TELEMETRY_WINDOW = timedelta(hours=24)
_SEARCH_TERM_MAX = 256
_NOT_REQUESTED_CODES: Final = frozenset(
    {"no_required_capabilities", "no_preferred_tags", "no_context_entities"}
)

PartialReason = Literal["limit", "timeout_ms"]


class AgentMatchReader(Protocol):
    """Port for consumers (the API, the copilot tool); ``AgentMatcher`` satisfies it."""

    async def match(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> AgentMatchResponse: ...


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The contract response plus what the contract has no field for (per-candidate values)."""

    response: AgentMatchResponse
    confidence: Mapping[str, float] = field(default_factory=dict)
    """Entity id to relative confidence in 0-1 (not a probability)."""
    cold_start: Mapping[str, bool] = field(default_factory=dict)
    """Entity id to whether that candidate had no observed telemetry."""


@dataclass(frozen=True, slots=True)
class _Reach:
    hops: int
    edge_type: str
    other_id: str | None
    direction: Literal["outgoing", "incoming"] | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    entity_id: str
    entity_type: Literal["agent", "tool"]
    domain_id: str
    display_name: str
    lifecycle_status: str
    tags: tuple[str, ...]
    capabilities: tuple[str, ...]


def _s(value: Any) -> str:
    """Plain string of a contract scalar (RootModel wrappers expose ``root``)."""
    while hasattr(value, "root"):  # CanonicalId and friends wrap more than once
        value = value.root
    return str(value)


def _strings(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    items = getattr(values, "root", values)
    return tuple(_s(v) for v in items or ())


def _as_candidate(entity: CatalogEntity) -> _Candidate | None:
    ent: Any = entity  # only agents and tools carry the fields read below
    etype = getattr(ent, "entity_type", None)
    if etype == "agent":
        kind: Literal["agent", "tool"] = "agent"
    elif etype == "tool":
        kind = "tool"
    else:
        return None
    return _Candidate(
        entity_id=_s(ent.id),
        entity_type=kind,
        domain_id=_s(ent.domain_id),
        display_name=_s(ent.display_name),
        lifecycle_status=_s(ent.lifecycle_status),
        tags=_strings(getattr(ent, "tags", None)),
        capabilities=_strings(getattr(ent, "capabilities", None)),
    )


def _env_of(entity: CatalogEntity) -> str:
    env = getattr(entity, "environment", None)
    return "unknown" if env is None else _s(env)


def _with_detail(value: SignalValue, detail: str) -> SignalValue:
    return value.model_copy(update={"detail_code": detail})


def _search_term(*token_groups: Sequence[str]) -> str:
    seen: dict[str, None] = {}
    for group in token_groups:
        for token in group:
            seen.setdefault(token, None)
    parts: list[str] = []
    size = 0
    for token in seen:
        if size + len(token) + (1 if parts else 0) > _SEARCH_TERM_MAX:
            break
        parts.append(token)
        size += len(token) + (1 if len(parts) > 1 else 0)
    return " ".join(parts)


def _walk_reaches(anchor: str, edges: Sequence[Any], max_hops: int) -> dict[str, _Reach]:
    """Shortest hop count from ``anchor`` to every node of a bounded walk result.

    Hidden (curated-rejected) edges are skipped. Neighbors are visited in a fixed order so the
    kept edge type and previous node are deterministic.
    """
    adjacency: dict[str, list[tuple[str, str, Literal["outgoing", "incoming"]]]] = defaultdict(list)
    for edge in edges:
        if edge.hidden:
            continue
        adjacency[edge.source_id].append((edge.target_id, edge.relation_type, "incoming"))
        adjacency[edge.target_id].append((edge.source_id, edge.relation_type, "outgoing"))
    reaches: dict[str, _Reach] = {anchor: _Reach(0, "self", None, None)}
    queue: deque[str] = deque([anchor])
    while queue:
        node = queue.popleft()
        hops = reaches[node].hops
        if hops >= max_hops:
            continue
        for other, edge_type, direction in sorted(adjacency.get(node, ())):
            if other in reaches:
                continue
            # ``direction`` is the direction of the edge seen from the reached node (``other``).
            reaches[other] = _Reach(hops + 1, edge_type, node, direction)
            queue.append(other)
    return reaches


class AgentMatcher:
    """Ranks catalog agents and tools for a task. A recommendation only: nothing is invoked."""

    def __init__(
        self,
        search: AuthorizedSearch,
        graph: GraphQuery,
        feedback: FeedbackStore,
        *,
        subjects: SubjectMetricsReader | None = None,
        principal_pseudonym: Callable[[IdentityScope], str] | None = None,
        settings: MatchSettings | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        time_budget_ms: int = 1500,
        search_timeout_ms: int = 1000,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._search = search
        self._graph = graph
        self._feedback = feedback
        self._subjects = subjects
        self._pseudonym = principal_pseudonym or _scope_pseudonym
        self._settings = settings or MatchSettings()
        self._clock = clock
        self._monotonic = monotonic
        self._time_budget_s = time_budget_ms / 1000.0
        self._search_timeout_ms = max(1, min(30000, search_timeout_ms))
        self._id_factory = id_factory

    # ------------------------------------------------------------------ public API

    async def match(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> AgentMatchResponse:
        return (await self.match_detailed(scope, domain, request)).response

    async def match_detailed(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> MatchResult:
        self._require_domain(scope, domain)
        started = self._monotonic()
        deadline = started + self._time_budget_s
        reasons: set[PartialReason] = set()

        anchors = list(dict.fromkeys(_s(i) for i in (request.context_entity_ids or ())))
        await self._require_context_in_scope(scope, anchors)  # refuse, never ignore

        types = [str(t) for t in (request.candidate_types or ["agent"])]
        required_caps = [_s(c) for c in (request.required_capabilities or ())]
        preferred_tags = [_s(t) for t in (request.preferred_tags or ())]
        task_tokens = normalize_tokens(request.task_text)

        hit_scores: dict[str, float] = {}
        if task_tokens or required_caps or preferred_tags:
            hit_scores = await self._candidate_hits(
                scope,
                types,
                _search_term(
                    task_tokens,
                    *(normalize_tokens(t) for t in preferred_tags),
                    *(normalize_tokens(c) for c in required_caps),
                ),
                reasons,
            )

        env = None if request.environment is None else _s(request.environment)
        candidates = await self._fetch_candidates(scope, hit_scores, types, env)

        points, telemetry_reasons = await self._telemetry(scope, candidates, deadline, reasons)
        pool_median = latency_pool_median(points.values())

        max_depth = min(2, request.max_graph_depth if request.max_graph_depth is not None else 2)
        reach = await self._proximity(scope, anchors, max_depth, deadline, reasons)

        records = await self._list_feedback(scope, domain, candidates)
        by_entity: dict[str, list[FeedbackRecord]] = defaultdict(list)
        for record in records:
            by_entity[record.entity_id].append(record)

        weights = {k: v for k, v in self._settings.weights.items() if k != "feedback_prior"}
        bound = self._settings.feedback_bound
        now = self._clock()
        scored: list[tuple[str, CombinedResult]] = []
        for cand in sorted(candidates, key=lambda c: c.entity_id):
            values = self._signal_values(
                cand,
                hit_scores,
                required_caps,
                preferred_tags,
                points.get(cand.entity_id),
                pool_median,
                telemetry_reasons.get(cand.entity_id),
                reach,
                anchors,
                max_depth,
            )
            base = combine(values, weights)
            fb = feedback_signal(
                by_entity.get(cand.entity_id, ()),
                candidate_id=cand.entity_id,
                task_tokens=task_tokens,
                bound=bound,
                min_principals=self._settings.min_principals,
                ttl_days=self._settings.feedback_ttl_days,
                now=now,
            )
            scored.append((cand.entity_id, self._apply_feedback(base, fb.prior, fb.detail_code)))

        ranked = rank_candidates(scored)[: request.limit or 10]
        by_id = {c.entity_id: c for c in candidates}
        out: list[dict[str, Any]] = []
        confidence: dict[str, float] = {}
        cold: dict[str, bool] = {}
        for rank, (entity_id, res) in enumerate(ranked, start=1):
            cand = by_id[entity_id]
            sv = {s.signal: s for s in res.signal_values}
            relations = self._relations(entity_id, reach, anchors)
            out.append(
                {
                    "rank": rank,
                    "entity_id": entity_id,
                    "entity_type": cand.entity_type,
                    "display_name": cand.display_name,
                    "lifecycle_status": cand.lifecycle_status,
                    "score": res.score,
                    "signals": [s.model_dump(mode="json") for s in res.contributions],
                    "matched_capabilities": list(sv["capability_match"].matched)
                    if "capability_match" in sv
                    else [],
                    "matched_tags": list(sv["tag_match"].matched) if "tag_match" in sv else [],
                    "relations": relations,
                    "evidence_ids": [],
                }
            )
            confidence[entity_id] = res.confidence
            cold[entity_id] = res.cold_start

        if self._monotonic() > deadline:
            reasons.add("timeout_ms")
        reason: PartialReason | None = (
            "timeout_ms" if "timeout_ms" in reasons else ("limit" if reasons else None)
        )
        match_id = f"m-{self._id_factory()}"
        if ranked:
            await self._feedback.record_match(
                MatchRecord(
                    match_id=match_id,
                    customer_id=scope.customer_id,
                    domain_id=domain,
                    principal=self._pseudonym(scope),
                    task_tokens=task_tokens,
                    candidates=tuple(
                        MatchCandidateRecord(entity_id, rank, res.score)
                        for rank, (entity_id, res) in enumerate(ranked, start=1)
                    ),
                    created_at=now,
                    expires_at=now + timedelta(days=self._settings.feedback_ttl_days),
                )
            )
        response = AgentMatchResponse.model_validate(
            {
                "schema_version": "1.0.0",
                "match_id": match_id,
                "domain_id": domain,
                "generated_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "ranker": {"ranker_id": RANKER_ID, "ranker_version": RANKER_VERSION},
                "cold_start": bool(ranked) and all(r.cold_start for _, r in ranked),
                "signals_unavailable": self._unavailable(ranked),
                "candidates": out,
                "truncated": reason is not None,
                "partial_reason": reason,
            }
        )
        return MatchResult(response=response, confidence=confidence, cold_start=cold)

    async def record_feedback(
        self, scope: IdentityScope, domain: str, request: AgentMatchFeedbackRequest
    ) -> FeedbackRecord:
        """Store or replace the caller's decision. Raises ``ForbiddenError`` (domain outside the
        scope), ``MatchNotFoundError`` (unknown, expired or not theirs) or
        ``CandidateNotInMatchError`` (candidate not in that match)."""
        self._require_domain(scope, domain)
        return await self._feedback.record_feedback(
            customer_id=scope.customer_id,
            domain_id=domain,
            match_id=request.match_id,
            principal=self._pseudonym(scope),
            entity_id=_s(request.entity_id),
            decision=request.decision,
            reason_code=request.reason_code,
        )

    async def metrics(
        self, scope: IdentityScope, domain: str, since: datetime, until: datetime
    ) -> FeedbackMetrics:
        self._require_domain(scope, domain)
        return await self._feedback.metrics(
            customer_id=scope.customer_id, domain_ids=[domain], since=since, until=until
        )

    # ------------------------------------------------------------------ stages

    @staticmethod
    def _require_domain(scope: IdentityScope, domain: str) -> None:
        if domain not in scope.allowed_domains:
            raise ForbiddenError(reason="domain_out_of_scope")

    async def _require_context_in_scope(self, scope: IdentityScope, anchors: Sequence[str]) -> None:
        if not anchors:
            return
        found = await asyncio.gather(*(self._graph.get(scope, a) for a in anchors))
        if any(entity is None for entity in found):
            raise ForbiddenError(reason="context_entity_out_of_scope")

    async def _candidate_hits(
        self, scope: IdentityScope, types: Sequence[str], term: str, reasons: set[PartialReason]
    ) -> dict[str, float]:
        if not term:
            return {}
        cap = min(self._settings.candidate_cap, 1000)
        entities: list[Any] = list(types)
        result = await self._search.search(
            scope.to_contract(),
            SearchRequest(
                term=term,
                filters=SearchFilters(entities=entities),
                budget=Budget(timeout_ms=self._search_timeout_ms, limit=cap, max_depth=0),
            ),
        )
        if result.partial:
            reasons.add("timeout_ms" if result.partial_reason == "timeout_ms" else "limit")
        return {h.id: h.score for h in result.hits[:cap]}

    async def _fetch_candidates(
        self,
        scope: IdentityScope,
        hit_scores: Mapping[str, float],
        types: Sequence[str],
        env: str | None,
    ) -> list[_Candidate]:
        """Re-fetch each hit with the caller's scope; anything not returned never surfaces."""
        ids = sorted(hit_scores)
        fetched = await asyncio.gather(*(self._graph.get(scope, i) for i in ids))
        out: list[_Candidate] = []
        for entity in fetched:
            if entity is None:
                continue
            cand = _as_candidate(entity)
            if cand is None or cand.entity_type not in types:
                continue
            if env is not None and _env_of(entity) != env:
                continue
            out.append(cand)
        return out

    async def _telemetry(
        self,
        scope: IdentityScope,
        candidates: Sequence[_Candidate],
        deadline: float,
        reasons: set[PartialReason],
    ) -> tuple[dict[str, SubjectPoint], dict[str, str]]:
        """Points per agent id and a reason code for every candidate without one.

        At most one aggregate read per domain and at most ``MAX_TELEMETRY_DOMAINS`` domains.
        """
        points: dict[str, SubjectPoint] = {}
        why: dict[str, str] = {}
        by_domain: dict[str, list[str]] = defaultdict(list)
        for cand in candidates:
            if cand.entity_type == "tool":
                why[cand.entity_id] = "tool_has_no_aggregates"
            else:
                by_domain[cand.domain_id].append(cand.entity_id)
        if not by_domain:
            return points, why
        reader = self._subjects
        if reader is None:
            for ids in by_domain.values():
                for i in ids:
                    why[i] = "telemetry_reader_missing"
            return points, why

        ordered = sorted(by_domain, key=lambda d: (-len(by_domain[d]), d))
        for domain_id in ordered[MAX_TELEMETRY_DOMAINS:]:
            reasons.add("limit")
            for i in by_domain[domain_id]:
                why[i] = "telemetry_domain_cap"
        end = bucket_start(self._clock(), "hour") + timedelta(hours=1)
        window = AggregateWindow(start=end - _TELEMETRY_WINDOW, end=end)

        async def read(domain_id: str) -> None:
            ids = by_domain[domain_id]
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                reasons.add("timeout_ms")
                for i in ids:
                    why[i] = "telemetry_time_budget"
                return
            keys = {subject_series_key("agent", i): i for i in ids[:MAX_SUBJECT_KEYS_PER_READ]}
            try:
                found = await asyncio.wait_for(
                    reader.latest_subject_points(
                        scope.customer_id, domain_id, "agent", sorted(keys), window
                    ),
                    remaining,
                )
            except Exception as exc:  # degrade, never fail the match; log the type only
                _log.warning("agent match telemetry read failed: %s", type(exc).__name__)
                for i in ids:
                    why[i] = "telemetry_read_failed"
                return
            if found.truncated or len(ids) > MAX_SUBJECT_KEYS_PER_READ:
                reasons.add("limit")
            for key, point in found.points.items():
                if key in keys:
                    points[keys[key]] = point

        await asyncio.gather(*(read(d) for d in ordered[:MAX_TELEMETRY_DOMAINS]))
        for ids in by_domain.values():
            for i in ids:
                if i not in points:
                    why.setdefault(i, "no_telemetry")
        return points, why

    async def _proximity(
        self,
        scope: IdentityScope,
        anchors: Sequence[str],
        max_depth: int,
        deadline: float,
        reasons: set[PartialReason],
    ) -> dict[str, dict[str, _Reach]] | None:
        """Per anchor, the reach of every node within ``max_depth``; None when it failed.

        One bounded walk per anchor (none at depth 0: only the anchors themselves are near).
        """
        if not anchors:
            return {}
        if max_depth == 0:
            return {a: {a: _Reach(0, "self", None, None)} for a in anchors}
        remaining_ms = int((deadline - self._monotonic()) * 1000)
        if remaining_ms <= 0:
            reasons.add("timeout_ms")
            return None
        budget = Budget(
            timeout_ms=max(1, min(remaining_ms, 5000)),
            limit=100,
            max_depth=max_depth,
            max_nodes=1000,
            max_edges=4000,
        )

        async def walk(anchor: str) -> dict[str, _Reach] | None:
            try:
                result = await self._graph.neighbors(
                    scope, NeighborsRequest(node_id=anchor, direction="both", budget=budget)
                )
            except Exception as exc:  # degrade, never fail the match
                _log.warning("agent match graph walk failed: %s", type(exc).__name__)
                return None
            if result.truncated and result.truncated_reason == "timeout_ms":
                reasons.add("timeout_ms")
            elif result.truncated and result.truncated_reason in ("max_nodes", "max_edges"):
                reasons.add("limit")
            return _walk_reaches(anchor, result.edges, max_depth)

        walked = await asyncio.gather(*(walk(a) for a in anchors))
        out: dict[str, dict[str, _Reach]] = {}
        for anchor, reaches in zip(anchors, walked, strict=True):
            if reaches is None:
                return None
            out[anchor] = reaches
        return out

    async def _list_feedback(
        self, scope: IdentityScope, domain: str, candidates: Sequence[_Candidate]
    ) -> tuple[FeedbackRecord, ...]:
        """Feedback is stored under the domain the match was made through (``domain``), not the
        candidate's own domain, so that is where it is read back."""
        if not candidates:
            return ()
        entity_ids = [c.entity_id for c in candidates][:1000]
        return await self._feedback.list_feedback(
            customer_id=scope.customer_id, domain_ids=[domain], entity_ids=entity_ids
        )

    # ------------------------------------------------------------------ scoring

    def _signal_values(
        self,
        cand: _Candidate,
        hit_scores: Mapping[str, float],
        required_caps: Sequence[str],
        preferred_tags: Sequence[str],
        point: SubjectPoint | None,
        pool_median: float | None,
        telemetry_reason: str | None,
        reach: Mapping[str, Mapping[str, _Reach]] | None,
        anchors: Sequence[str],
        max_depth: int,
    ) -> list[SignalValue]:
        cap, tag = tag_signal(cand.tags, cand.capabilities, required_caps, preferred_tags)
        text = lexical_signal(cand.entity_id, hit_scores)
        success, latency, usage = telemetry_signal(point, pool_median)
        if point is None and telemetry_reason is not None:
            success, latency, usage = (
                _with_detail(v, telemetry_reason) for v in (success, latency, usage)
            )
        if not anchors:
            proximity = proximity_signal(None)
        elif reach is None:
            proximity = SignalValue(
                signal="graph_proximity", value=None, detail_code="proximity_unavailable"
            )
        else:
            paths = [
                ProximityPath(hops=r.hops, edge_type=r.edge_type)
                for per_anchor in reach.values()
                if (r := per_anchor.get(cand.entity_id)) is not None
            ]
            proximity = proximity_signal(paths, max_depth)
        return [cap, tag, text, proximity, success, latency, usage]

    def _apply_feedback(self, base: CombinedResult, prior: float, detail: str) -> CombinedResult:
        """Add the bounded feedback prior (signed) on top of the combined score.

        Contributions still sum to the score: the applied prior is clipped so the score stays
        in 0-1. With insufficient evidence the signal is unobserved and contributes nothing.
        """
        bound = self._settings.feedback_bound
        if detail == "feedback_insufficient_evidence" or bound <= 0.0:
            value: float | None = None
            applied = 0.0
            weight = 0.0
        else:
            applied = min(1.0, max(0.0, base.score + prior)) - base.score
            value = min(1.0, max(0.0, 0.5 + prior / (2.0 * bound)))
            weight = min(1.0, bound)
        signal = AgentMatchSignal.model_validate(
            {
                "signal": "feedback_prior",
                "value": value,
                "weight": weight,
                "contribution": applied,
                "detail_code": detail,
            }
        )
        reading = SignalValue(signal="feedback_prior", value=value, detail_code=detail)
        unobserved = (*base.unobserved, "feedback_prior") if value is None else base.unobserved
        return base.model_copy(
            update={
                "score": min(1.0, max(0.0, base.score + applied)),
                "contributions": (*base.contributions, signal),
                "signal_values": (*base.signal_values, reading),
                "unobserved": unobserved,
            }
        )

    @staticmethod
    def _relations(
        entity_id: str, reach: Mapping[str, Mapping[str, _Reach]] | None, anchors: Sequence[str]
    ) -> list[dict[str, str]]:
        """The relationship that makes the candidate near an anchor (edge type, neighbor id)."""
        if not reach:
            return []
        best: _Reach | None = None
        for anchor in anchors:
            r = reach.get(anchor, {}).get(entity_id)
            if r is None or r.other_id is None or r.direction is None:
                continue
            if best is None or (r.hops, r.edge_type, r.other_id) < (
                best.hops,
                best.edge_type,
                best.other_id or "",
            ):
                best = r
        if best is None or best.other_id is None or best.direction is None:
            return []
        return [
            {
                "relation_type": best.edge_type,
                "entity_id": best.other_id,
                "direction": best.direction,
            }
        ]

    @staticmethod
    def _unavailable(ranked: Sequence[tuple[str, CombinedResult]]) -> list[str]:
        """Signals unobserved for every returned candidate, unless the request never asked."""
        if not ranked:
            return []
        out: list[str] = []
        for name in SIGNAL_NAMES:
            details: list[str | None] = []
            for _, res in ranked:
                reading = next((s for s in res.signal_values if s.signal == name), None)
                if reading is not None and reading.value is not None:
                    break
                details.append(None if reading is None else reading.detail_code)
            else:
                if not all(d in _NOT_REQUESTED_CODES for d in details):
                    out.append(name)
        return [n for n in out if n in SIGNAL_NAMES]


def _scope_pseudonym(scope: IdentityScope) -> str:
    """The scope's own principal pseudonym (already pseudonymous, never an identity)."""
    return scope.to_contract().principal.principal_pseudonym
