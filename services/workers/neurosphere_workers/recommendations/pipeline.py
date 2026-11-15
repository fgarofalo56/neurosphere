"""PRP-15 item 6: one worker entry point that turns a sandbox output directory into stored
recommendations.

Runs, for a server-derived ``IdentityScope``:

1. the bounded rules (cost spike, latency, error rate, unused agent) over ``SandboxSeriesSource``;
2. duplicate-agent candidates over the presented catalog (read-only ``GraphQuery``), loaded from
   the sandbox relation and entity files into an in-memory catalog that only this module writes
   (the detector itself never holds a write handle);
3. right-sizing projections from per-agent token usage summarized from the sandbox ``cost.ndjson``
   (estimated records, de-duplicated by ``dedupe_key``), a versioned candidate-pair config and a
   price snapshot store. A projection whose price version cannot be resolved is skipped and
   reported, never emitted.

Every record is ``put`` into the ``RecommendationStore``. Analytical work lives here, in the
worker, never in the API process. ``created_at`` is a parameter: this module reads no wall clock,
no network and no credential. Nothing here changes a target system; records are advisory.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation, TimeRange
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import EdgeFilter, EntityFilter, GraphQuery, NeighborsRequest
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import EDGE_MODELS, ENTITY_MODELS
from neurosphere_core.ledger.models import TokenCounts
from neurosphere_core.paging import PageRequest
from neurosphere_core.pricing import PriceSnapshotStore
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

from neurosphere_workers.recommendations.duplicates import (
    AgentLister,
    DuplicateConfig,
    DuplicateDetector,
    ReviewCandidate,
    SimilaritySignalProvider,
)
from neurosphere_workers.recommendations.projection import (
    CandidatePairConfig,
    SkippedProjection,
    UsageSummary,
    project_right_sizing_candidates,
)
from neurosphere_workers.recommendations.rules import (
    DEFAULT_RULES,
    AgentSeriesSource,
    ArchiveSeriesSource,
    RuleSet,
    SandboxSeriesSource,
    evaluate_rules,
    recommendations,
    window_ending,
)
from neurosphere_workers.runtime.archive_reader import ArchiveReader

__all__ = [
    "PipelineSummary",
    "load_sandbox_catalog",
    "run_pipeline",
    "run_pipeline_archive",
    "summarize_usage",
    "summarize_usage_docs",
]

_ENTITY_FILES = (
    "domains.ndjson",
    "owners.ndjson",
    "model_deployments.ndjson",
    "grounding_sources.ndjson",
    "tools.ndjson",
    "agents.ndjson",
)
_MAX_EVIDENCE_IDS = 200


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """What one run stored and what it deliberately did not."""

    window: tuple[date, date] | None
    """Observed telemetry window ``[start, end)``; ``None`` when the sandbox has no telemetry."""
    counts_by_kind: dict[str, int]
    stored: int
    rule_outcomes: dict[str, int]
    skipped_projections: tuple[SkippedProjection, ...]
    review_candidates: tuple[ReviewCandidate, ...]
    duplicate_truncated: bool
    duplicate_truncation_reasons: tuple[str, ...]
    usage_summaries: int
    stored_ids: tuple[str, ...] = field(default=())
    archive_truncated: bool = False
    """Archive mode: the listing or per-run bound was hit, so coverage is unknown."""
    archive_skipped: int = 0
    """Archive mode: blobs and documents skipped (unreadable, malformed, invalid)."""


def _read_ndjson(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                yield json.loads(text)


async def load_sandbox_catalog(
    directory: Path, *, scope: IdentityScope
) -> tuple[RepositoryGraphQuery, InMemoryCatalogRepository]:
    """Load the sandbox entities and relations of ``scope``'s domains into a fresh in-memory
    catalog. Documents of other clouds, customers or domains are not loaded (fail closed).

    The returned repository is handed to the read-only duplicate detector as an ``AgentLister``;
    this function is the only writer.
    """
    allowed = frozenset(scope.allowed_domains)

    def visible(doc: dict[str, Any]) -> bool:
        return (
            doc.get("cloud") == scope.cloud
            and doc.get("customer_id") == scope.customer_id
            and doc.get("domain_id") in allowed
        )

    repo = InMemoryCatalogRepository()
    loaded: list[dict[str, Any]] = []
    for name in _ENTITY_FILES:
        for doc in _read_ndjson(directory / name):
            if visible(doc):
                model = ENTITY_MODELS[doc["entity_type"]].model_validate(doc)
                await repo.create_entity(scope, model)  # type: ignore[arg-type]
                loaded.append(model.model_dump(mode="json"))
    for doc in _read_ndjson(directory / "relations.ndjson"):
        if visible(doc):
            edge = EDGE_MODELS[doc["relation_type"]].model_validate(doc)
            await repo.put_edge(scope, edge, None)  # type: ignore[arg-type]
    # The pipeline never searches, but the graph is built over a real in-scope index (only the
    # entities loaded above, i.e. already filtered to ``scope``) so no stub can mask a misuse.
    index = FixtureSearchIndex(documents_from_catalog(loaded))
    return RepositoryGraphQuery(repo, index), repo


def _iso(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_usage(
    directory: Path,
    *,
    scope: IdentityScope,
    window: tuple[date, date],
    source: AgentSeriesSource,
) -> list[UsageSummary]:
    """Per agent and model token usage from the sandbox ``cost.ndjson`` (see
    ``summarize_usage_docs``)."""
    return summarize_usage_docs(
        _read_ndjson(directory / "cost.ndjson"), scope=scope, window=window, source=source
    )


def summarize_usage_docs(
    docs: Iterable[dict[str, Any]],
    *,
    scope: IdentityScope,
    window: tuple[date, date],
    source: AgentSeriesSource,
) -> list[UsageSummary]:
    """Per agent and model token usage from cost documents.

    Only ``estimated`` records that carry a token breakdown are summed (invoiced billing rows have
    no tokens); gateway and application views of one request share a ``dedupe_key`` and count
    once. Agents outside the scope are never summarized. Output is sorted for determinism.
    """
    allowed = frozenset(scope.allowed_domains)
    start, end = window
    series = {
        s.agent_id: s
        for s in source.series(
            cloud=scope.cloud,
            customer_id=scope.customer_id,
            domain_ids=allowed,
            start=start,
            end=end,
        )
    }
    totals: dict[tuple[str, str, str, str | None], list[int]] = {}
    evidence: dict[tuple[str, str, str, str | None], list[str]] = {}
    seen: set[str] = set()
    for doc in docs:
        if doc.get("kind") != "estimated" or "token_breakdown" not in doc:
            continue
        agent_id = doc.get("canonical_agent_id")
        if not isinstance(agent_id, str) or agent_id not in series:
            continue
        item = series[agent_id]
        if (
            doc.get("cloud") != scope.cloud
            or doc.get("customer_id") != scope.customer_id
            or item.domain_id not in allowed
        ):
            continue
        dedupe = doc.get("dedupe_key")
        if isinstance(dedupe, str):
            if dedupe in seen:
                continue
            seen.add(dedupe)
        provider, model = doc.get("provider"), doc.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        version = doc.get("model_version")
        key = (agent_id, provider, model, version if isinstance(version, str) else None)
        tokens = doc["token_breakdown"]
        acc = totals.setdefault(key, [0, 0, 0])
        acc[0] += int(tokens.get("input", 0))
        acc[1] += int(tokens.get("output", 0))
        acc[2] += int(tokens.get("cached", 0))
        ids = evidence.setdefault(key, [])
        cost_id = doc.get("cost_id")
        if isinstance(cost_id, str) and len(ids) < _MAX_EVIDENCE_IDS:
            ids.append(cost_id)

    window_start = datetime.combine(start, time.min, tzinfo=UTC)
    window_end = datetime.combine(end, time.min, tzinfo=UTC)
    summaries: list[UsageSummary] = []
    for key in sorted(totals, key=lambda k: (k[0], k[1], k[2], k[3] or "")):
        agent_id, provider, model, version = key
        item = series[agent_id]
        covered = sum(1 for d in item.days if d.covered)
        total_days = max(len(item.days), 1)
        fraction = covered / total_days
        method = "full" if covered == total_days else "partial" if covered else "unknown"
        tin, tout, tcached = totals[key]
        summaries.append(
            UsageSummary(
                agent_id=agent_id,
                cloud=scope.cloud,  # type: ignore[arg-type]
                customer_id=scope.customer_id,
                domain_id=item.domain_id,
                owner_id=item.owner_id,
                provider=provider,
                current_model=model,
                current_model_version=version,
                tokens=TokenCounts(input=tin, output=tout, cached=tcached),
                window_start=window_start,
                window_end=window_end,
                evidence_ids=tuple(dict.fromkeys(evidence.get(key, []))),
                coverage_method=method,  # type: ignore[arg-type]
                observed_fraction=fraction if method != "unknown" else None,
            )
        )
    return summaries


async def run_pipeline(
    directory: Path,
    *,
    scope: IdentityScope,
    store: RecommendationStore,
    prices: PriceSnapshotStore,
    pairs: CandidatePairConfig,
    created_at: datetime,
    rules: RuleSet = DEFAULT_RULES,
    duplicate_config: DuplicateConfig | None = None,
    signal_provider: SimilaritySignalProvider | None = None,
) -> PipelineSummary:
    """Run rules, duplicates and right-sizing projections for ``scope`` and store every record.

    ``directory`` is a sandbox output directory. ``scope`` is the server-derived scope: only its
    cloud, customer and allowed domains are read. ``created_at`` stamps every record (no wall
    clock). Duplicates run once for the whole scope (a pair is only ever formed inside one
    domain; model deployments homed in another allowed domain are then observed, not unknown).
    """
    source = SandboxSeriesSource(directory)
    window = source.observed_window()
    if window is None:
        return PipelineSummary(
            window=None,
            counts_by_kind={},
            stored=0,
            rule_outcomes={},
            skipped_projections=(),
            review_candidates=(),
            duplicate_truncated=False,
            duplicate_truncation_reasons=(),
            usage_summaries=0,
        )

    graph, repo = await load_sandbox_catalog(directory, scope=scope)
    usages = summarize_usage(directory, scope=scope, window=window, source=source)
    return await _evaluate_and_store(
        source,
        window,
        graph,
        repo,
        usages,
        scope=scope,
        store=store,
        prices=prices,
        pairs=pairs,
        created_at=created_at,
        rules=rules,
        duplicate_config=duplicate_config,
        signal_provider=signal_provider,
    )


def default_lookback_days(rules: RuleSet = DEFAULT_RULES) -> int:
    """The longest window any rule looks at (the archive window when none is configured)."""
    return max(
        rules.cost_spike.lookback_days,
        rules.latency_degradation.lookback_days,
        rules.error_rate_degradation.lookback_days,
        rules.unused_agent.window_days,
    )


_ARCHIVE_LIFECYCLE: list[Literal["draft", "active", "deprecated"]] = [
    "draft",
    "active",
    "deprecated",
]
_MAX_CATALOG_AGENTS = 5_000
_MAX_OWNER_EDGES = 50


def _text(value: Any) -> str:
    """Contract scalars are plain strings or single-field root models; return the string."""
    return str(getattr(value, "root", value))


async def _catalog_agents(
    graph: GraphQuery, lister: AgentLister, scope: IdentityScope
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Agents and owners of ``scope`` from the live catalog (read-only calls only).

    The owner of an agent is its ``owned_by`` target, an asserted edge before an inferred one and
    then the smallest target id, the rule the sandbox source uses.
    """
    allowed = list(scope.allowed_domains)
    if not allowed:
        return [], {}
    flt = EntityFilter(
        entity_types=["agent"], domain_ids=allowed, lifecycle_statuses=list(_ARCHIVE_LIFECYCLE)
    )
    agents: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(agents) < _MAX_CATALOG_AGENTS:
        page = await lister.list_entities(scope, flt, PageRequest(page_size=500, cursor=cursor))
        for entity in page.items:
            if (
                getattr(entity, "entity_type", None) != "agent"
                or _text(getattr(entity, "customer_id", "")) != scope.customer_id
                or _text(getattr(entity, "cloud", "")) != scope.cloud
                or _text(getattr(entity, "domain_id", "")) not in allowed
            ):
                continue
            created = getattr(entity, "created_at", None)  # datetime or RFC 3339 root model
            agents.append(
                {
                    "id": _text(getattr(entity, "id", "")),
                    "cloud": scope.cloud,
                    "customer_id": scope.customer_id,
                    "domain_id": _text(getattr(entity, "domain_id", "")),
                    "lifecycle_status": _text(getattr(entity, "lifecycle_status", "unknown")),
                    "created_at": None if created is None else _text(created),
                }
            )
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    owners: dict[str, str] = {}
    for agent in agents:
        result = await graph.neighbors(
            scope,
            NeighborsRequest(
                node_id=agent["id"],
                direction="out",
                filters=EdgeFilter(relation_types=["owned_by"]),
                budget=Budget(timeout_ms=2_000, limit=_MAX_OWNER_EDGES, max_depth=1),
                view="presented",
            ),
        )
        chosen: tuple[int, str] | None = None
        for edge in result.edges:
            if edge.hidden or edge.source_id != agent["id"] or edge.relation_type != "owned_by":
                continue
            rank = (0 if edge.status == "asserted" else 1, edge.target_id)
            if chosen is None or rank < chosen:
                chosen = rank
        if chosen is not None:
            owners[agent["id"]] = chosen[1]
    return agents, owners


async def run_pipeline_archive(
    reader: ArchiveReader,
    *,
    graph: GraphQuery,
    lister: AgentLister,
    scope: IdentityScope,
    store: RecommendationStore,
    prices: PriceSnapshotStore,
    pairs: CandidatePairConfig,
    created_at: datetime,
    lookback_days: int | None = None,
    rules: RuleSet = DEFAULT_RULES,
    duplicate_config: DuplicateConfig | None = None,
    signal_provider: SimilaritySignalProvider | None = None,
    max_docs: int | None = None,
) -> PipelineSummary:
    """Rules, duplicates and right-sizing over the live catalog and the redacted archive.

    Agents, owners and duplicate candidates come from the live catalog through the read-only
    ``GraphQuery`` and ``AgentLister`` (nothing is written to it); telemetry and cost come from
    the archive window of the last ``lookback_days`` complete UTC days ending at ``created_at``'s
    date. A truncated archive makes coverage unknown (no ``unused_agent``) and is reported in
    ``PipelineSummary.archive_truncated``. No wall clock is read: ``created_at`` is a parameter.
    """
    days = lookback_days if lookback_days is not None else default_lookback_days(rules)
    window = window_ending(created_at.astimezone(UTC).date(), days)
    agents, owners = await _catalog_agents(graph, lister, scope)
    extra = {} if max_docs is None else {"max_docs": max_docs}
    source = await ArchiveSeriesSource.load(
        reader, scope=scope, agents=agents, owners=owners, window=window, **extra
    )
    usages = summarize_usage_docs(source.usage_docs, scope=scope, window=window, source=source)
    stats, tele = source.archive_stats, source.stats
    skipped = stats.unreadable + stats.malformed + tele.telemetry_skipped + tele.cost_skipped
    return await _evaluate_and_store(
        source,
        window,
        graph,
        lister,
        usages,
        scope=scope,
        store=store,
        prices=prices,
        pairs=pairs,
        created_at=created_at,
        rules=rules,
        duplicate_config=duplicate_config,
        signal_provider=signal_provider,
        archive_truncated=source.truncated,
        archive_skipped=skipped,
    )


async def _evaluate_and_store(
    source: AgentSeriesSource,
    window: tuple[date, date],
    graph: GraphQuery,
    lister: AgentLister,
    usages: list[UsageSummary],
    *,
    scope: IdentityScope,
    store: RecommendationStore,
    prices: PriceSnapshotStore,
    pairs: CandidatePairConfig,
    created_at: datetime,
    rules: RuleSet,
    duplicate_config: DuplicateConfig | None,
    signal_provider: SimilaritySignalProvider | None,
    archive_truncated: bool = False,
    archive_skipped: int = 0,
) -> PipelineSummary:
    records: list[Recommendation] = []

    results = evaluate_rules(
        source,
        scope=scope,
        window_start=window[0],
        window_end=window[1],
        created_at=created_at,
        rules=rules,
    )
    records.extend(recommendations(results))
    outcomes = Counter(r.outcome for r in results)

    detector = DuplicateDetector(graph, lister, duplicate_config, signal_provider=signal_provider)
    run = await detector.run(
        scope=scope,
        window=TimeRange.model_validate({"start": _iso(window[0]), "end": _iso(window[1])}),
        created_at=created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    records.extend(c.recommendation for c in run.candidates)

    batch = project_right_sizing_candidates(usages, pairs, prices, created_at=created_at)
    records.extend(batch.recommendations)

    ids: list[str] = []
    kinds: Counter[str] = Counter()
    for record in records:
        await store.put(record)
        ids.append(record.recommendation_id.root)
        kinds[record.kind] += 1

    return PipelineSummary(
        window=window,
        counts_by_kind=dict(sorted(kinds.items())),
        stored=len(records),
        rule_outcomes=dict(sorted(outcomes.items())),
        skipped_projections=batch.skipped,
        review_candidates=run.review_candidates,
        duplicate_truncated=run.truncated,
        duplicate_truncation_reasons=run.truncation_reasons,
        usage_summaries=len(usages),
        stored_ids=tuple(ids),
        archive_truncated=archive_truncated,
        archive_skipped=archive_skipped,
    )
