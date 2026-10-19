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
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation, TimeRange
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import EDGE_MODELS, ENTITY_MODELS
from neurosphere_core.ledger.models import TokenCounts
from neurosphere_core.pricing import PriceSnapshotStore
from neurosphere_core.recommendations import RecommendationStore
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.duplicates import (
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
    RuleSet,
    SandboxSeriesSource,
    evaluate_rules,
    recommendations,
)

__all__ = ["PipelineSummary", "load_sandbox_catalog", "run_pipeline", "summarize_usage"]

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
    for name in _ENTITY_FILES:
        for doc in _read_ndjson(directory / name):
            if visible(doc):
                model = ENTITY_MODELS[doc["entity_type"]].model_validate(doc)
                await repo.create_entity(scope, model)  # type: ignore[arg-type]
    for doc in _read_ndjson(directory / "relations.ndjson"):
        if visible(doc):
            edge = EDGE_MODELS[doc["relation_type"]].model_validate(doc)
            await repo.put_edge(scope, edge, None)  # type: ignore[arg-type]
    return RepositoryGraphQuery(repo, _NoSearch()), repo  # type: ignore[arg-type]


class _NoSearch:
    """``GraphQuery.neighbors`` never searches; the pipeline does not either."""

    async def search(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the recommendations pipeline must not use search")


def _iso(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_usage(
    directory: Path,
    *,
    scope: IdentityScope,
    window: tuple[date, date],
    source: SandboxSeriesSource,
) -> list[UsageSummary]:
    """Per agent and model token usage from the sandbox ``cost.ndjson``.

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
    for doc in _read_ndjson(directory / "cost.ndjson"):
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

    records: list[Recommendation] = []

    results = evaluate_rules(
        source,
        scope=scope,
        window_start=window[0],
        window_end=window[1],
        created_at=created_at,
    )
    records.extend(recommendations(results))
    outcomes = Counter(r.outcome for r in results)

    graph, repo = await load_sandbox_catalog(directory, scope=scope)
    detector = DuplicateDetector(graph, repo, duplicate_config, signal_provider=signal_provider)
    run = await detector.run(
        scope=scope,
        window=TimeRange.model_validate({"start": _iso(window[0]), "end": _iso(window[1])}),
        created_at=created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    records.extend(c.recommendation for c in run.candidates)

    usages = summarize_usage(directory, scope=scope, window=window, source=source)
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
    )
