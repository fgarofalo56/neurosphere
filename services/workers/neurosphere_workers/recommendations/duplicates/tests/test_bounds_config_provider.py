"""Config validation, bounds (truncated flag), the optional signal provider, curated edges."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog.protocol import EdgeFilter, NeighborsRequest
from pydantic import ValidationError

from neurosphere_workers.recommendations.duplicates import (
    DuplicateConfig,
    DuplicateDetector,
    DuplicateRun,
    SignalWeights,
)

from .support import CREATED_AT, Estate, load_estate, make_scope, read_ndjson


def _domain_of_first_pair(estate: Estate) -> tuple[str, list[str]]:
    """Domain id and sorted agent ids of the first (sorted) ground-truth duplicate pair."""
    pair = sorted(min(estate.duplicate_pairs, key=sorted))
    domains = {a["id"]: a["domain_id"] for a in read_ndjson(estate.source_dir / "agents.ndjson")}
    return domains[pair[0]], pair


def _run(estate: Estate, domain: str, cfg: DuplicateConfig, **kw: Any) -> DuplicateRun:
    detector = DuplicateDetector(estate.graph, estate.repo, cfg, **kw)  # type: ignore[arg-type]
    return asyncio.run(
        detector.run(scope=make_scope([domain]), window=estate.window, created_at=CREATED_AT)
    )


# --------------------------------------------------------------------------- config


def test_config_is_frozen_versioned_and_forbids_extras() -> None:
    cfg = DuplicateConfig()
    assert cfg.generator_id
    assert cfg.version
    with pytest.raises(ValidationError):
        cfg.min_similarity = 0.1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DuplicateConfig.model_validate({"unknown_field": 1})
    with pytest.raises(ValidationError):
        SignalWeights.model_validate({"surprise": 0.5})


def test_review_floor_must_be_below_min_similarity() -> None:
    with pytest.raises(ValidationError):
        DuplicateConfig(min_similarity=0.6, review_floor=0.6)
    with pytest.raises(ValidationError):
        DuplicateConfig(min_similarity=0.6, review_floor=0.8)


def test_a_recommendation_cites_the_config_that_produced_it(
    estate: Estate, default_run: DuplicateRun
) -> None:
    cfg = DuplicateConfig(version="2.3.1", generator_id="duplicates.test-variant")
    domain, _ = _domain_of_first_pair(estate)
    run = _run(estate, domain, cfg)
    assert run.candidates
    for c in run.candidates:
        gen = c.recommendation.generator
        assert gen is not None
        assert (gen.generator_id.root, gen.generator_version.root) == (
            "duplicates.test-variant",
            "2.3.1",
        )
    # A different config version is a different recommendation id for the same pair.
    base_ids = {c.recommendation.recommendation_id.root for c in default_run.candidates}
    assert not base_ids & {c.recommendation.recommendation_id.root for c in run.candidates}


# --------------------------------------------------------------------------- bounds


def test_pair_cap_sets_the_truncated_flag(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    run = _run(estate, domain, DuplicateConfig(max_pairs_compared=3))
    assert run.pairs_compared == 3
    assert run.truncated is True
    assert "max_pairs_compared" in run.truncation_reasons


def test_candidate_cap_sets_the_truncated_flag(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    cfg = DuplicateConfig(min_similarity=0.5, review_floor=0.2, max_candidates=1)
    run = _run(estate, domain, cfg)
    assert len(run.candidates) == 1
    assert len(run.review_candidates) <= 1
    assert run.truncated is True
    assert "max_candidates" in run.truncation_reasons


def test_agent_cap_sets_the_truncated_flag(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    run = _run(estate, domain, DuplicateConfig(max_agents=4))
    assert run.agents_considered == 4
    assert run.truncated is True
    assert "max_agents" in run.truncation_reasons


def test_untruncated_run_says_so(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    run = _run(estate, domain, DuplicateConfig())
    assert run.truncated is False
    assert run.truncation_reasons == ()


def test_run_is_deterministic(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    first = _run(estate, domain, DuplicateConfig())
    second = _run(estate, domain, DuplicateConfig())
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


# --------------------------------------------------------------------------- provider


class FixedProvider:
    """Embedding stand-in: returns a fixed value (or None) and records what it was asked."""

    def __init__(self, value: float | None) -> None:
        self.value = value
        self.asked: set[str] = set()

    def similarity(self, agent_a: str, agent_b: str) -> float | None:
        self.asked.update((agent_a, agent_b))
        return self.value


def test_baseline_passes_without_a_provider_and_reports_no_embedding(
    default_run: DuplicateRun,
) -> None:
    assert default_run.candidates
    assert all(c.breakdown.embedding is None for c in default_run.candidates)
    assert all("embedding" not in c.breakdown.unobserved_signals for c in default_run.candidates)


def test_provider_is_optional_extra_signal_inside_the_scope(estate: Estate) -> None:
    domain, pair = _domain_of_first_pair(estate)
    provider = FixedProvider(1.0)
    run = _run(estate, domain, DuplicateConfig(), signal_provider=provider)
    assert provider.asked, "the provider was consulted"
    # Only agents of the caller's scope are ever sent to the provider.
    in_domain = {
        a["id"]
        for a in read_ndjson(estate.source_dir / "agents.ndjson")
        if a["domain_id"] == domain
    }
    assert provider.asked <= in_domain
    with_embedding = [c for c in run.candidates if c.breakdown.embedding is not None]
    assert with_embedding
    assert {frozenset(pair)} <= {
        frozenset(s.root for s in c.recommendation.subject_ids) for c in run.candidates
    }
    for c in with_embedding:
        assert c.breakdown.embedding == 1.0


def test_provider_without_a_vector_is_unobserved_not_zero(estate: Estate) -> None:
    domain, _ = _domain_of_first_pair(estate)
    run = _run(estate, domain, DuplicateConfig(), signal_provider=FixedProvider(None))
    assert run.candidates
    for c in run.candidates:
        assert c.breakdown.embedding is None
        assert "embedding" in c.breakdown.unobserved_signals
        assert c.recommendation.coverage.method == "partial"


# --------------------------------------------------------------------------- curated edges


def test_a_rejected_edge_is_hidden_from_the_presented_view_and_the_similarity(
    sandbox_dir: Path,
) -> None:
    """Curation shapes the presented lineage the job reads (and the job writes nothing)."""
    local = asyncio.run(load_estate(sandbox_dir))
    domain, pair = _domain_of_first_pair(local)
    scope = make_scope(local.domain_ids)
    first = _run(local, domain, DuplicateConfig())
    before = next(
        c
        for c in first.candidates
        if frozenset(s.root for s in c.recommendation.subject_ids) == frozenset(pair)
    )
    victim_source = before.breakdown.shared_source_ids[0]

    result = asyncio.run(
        local.graph.neighbors(
            scope,
            NeighborsRequest(
                node_id=pair[0],
                direction="out",
                filters=EdgeFilter(relation_types=["grounded_by"]),
                budget=Budget(timeout_ms=5000, limit=100, max_depth=1),
            ),
        )
    )
    presented = next(e for e in result.edges if e.target_id == victim_source)
    stored = asyncio.run(local.repo.get_edge(scope, presented.edge_id))
    assert stored is not None
    override = EdgeOverride.model_validate(
        {
            "schema_version": "1.0.0",
            "id": f"commercial:synthco:neurosphere:edge_override:{stored.id.split(':')[-1]}",
            "edge_id": stored.id,
            "relation_type": "grounded_by",
            "expected_edge_version": int(stored.version.root),
            "expected_edge_etag": stored.etag.root,
            "cloud": "commercial",
            "customer_id": "synthco",
            "domain_id": stored.domain_id.root,
            "decision": "reject",
            "actor": "commercial:synthco:entra:person:psn_0123456789abcdef",
            "reason": "Not a real grounding relation.",
            "decided_at": "2026-10-09T17:30:00Z",
            "lock": None,
            "set_confidence": None,
            "set_validity": None,
            "add_evidence_ids": [],
        }
    )
    asyncio.run(local.repo.put_override(scope, override))  # test setup: a steward rejects it

    second = _run(local, domain, DuplicateConfig())
    pairs_after = {
        frozenset(s.root for s in c.recommendation.subject_ids): c for c in second.candidates
    }
    after = pairs_after.get(frozenset(pair))
    if after is not None:
        assert victim_source not in after.breakdown.shared_source_ids
        assert presented.edge_id not in after.recommendation.evidence_ids
    # With a source no longer shared, the pair cannot keep the same similarity or evidence.
    assert after is None or after.breakdown.grounding_sources < before.breakdown.grounding_sources
