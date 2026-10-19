"""Scope: a scope for domain A never yields candidates or reads for domain B.

A pair is formed only within one domain (documented decision in ``detector.py``), so every
record carries exactly one ``domain_id`` that can be authorized against the scope.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from neurosphere_workers.recommendations.duplicates import DuplicateDetector, DuplicateRun

from .support import (
    CREATED_AT,
    Estate,
    ReadOnlyGraph,
    ReadOnlyLister,
    make_scope,
    read_ndjson,
)


def _agent_domains(sandbox_dir: Path) -> dict[str, str]:
    return {a["id"]: a["domain_id"] for a in read_ndjson(sandbox_dir / "agents.ndjson")}


def _domain_of_a_duplicate(estate: Estate, agent_domain: dict[str, str]) -> str:
    pair = sorted(next(iter(estate.duplicate_pairs)))
    domain = agent_domain[pair[0]]
    assert agent_domain[pair[1]] == domain, "sandbox duplicates live in one domain"
    return domain


def _run(
    estate: Estate, domains: list[str], **kw: object
) -> tuple[DuplicateRun, ReadOnlyGraph, ReadOnlyLister]:
    graph, lister = ReadOnlyGraph(estate.graph), ReadOnlyLister(estate.repo)
    detector = DuplicateDetector(graph, lister)  # type: ignore[arg-type]
    run = asyncio.run(
        detector.run(
            scope=make_scope(domains, **kw),  # type: ignore[arg-type]
            window=estate.window,
            created_at=CREATED_AT,
        )
    )
    return run, graph, lister


def test_domain_a_scope_reads_and_yields_nothing_from_domain_b(
    estate: Estate, sandbox_dir: Path
) -> None:
    agent_domain = _agent_domains(sandbox_dir)
    domain_a = _domain_of_a_duplicate(estate, agent_domain)
    run, graph, lister = _run(estate, [domain_a])

    # Reads: the listing is narrowed to A, and only agents of A were walked.
    assert [f.domain_ids for f in lister.filters] == [[domain_a]]
    walked = {r.node_id for r in graph.requests}
    assert walked
    assert {agent_domain[n] for n in walked} == {domain_a}
    in_a = {a for a, d in agent_domain.items() if d == domain_a and not a.endswith("none")}
    assert len(walked) <= len(in_a)

    # Results: every record and review candidate is domain A, both subjects included.
    assert run.candidates, "domain A holds a sandbox duplicate pair"
    for c in run.candidates:
        assert c.recommendation.domain_id.root == domain_a
        assert {agent_domain[s.root] for s in c.recommendation.subject_ids} == {domain_a}
    for r in run.review_candidates:
        assert r.domain_id == domain_a
        assert {agent_domain[s] for s in r.subject_ids} == {domain_a}
    # No evidence id points at another domain's relation.
    other_domains = {d for d in estate.domain_ids if d != domain_a}
    assert other_domains
    blob = json.dumps([c.model_dump(mode="json") for c in run.candidates])
    assert not any(d in blob for d in other_domains)


def test_pairs_never_span_domains_and_each_candidate_stays_in_a_scoped_domain(
    estate: Estate, sandbox_dir: Path
) -> None:
    """A multi-domain scope still forms pairs inside one domain, each in an allowed domain.

    (Results are deliberately NOT asserted equal to the union of single-domain runs: a
    narrower scope can hide a relation target homed in another domain, e.g. a shared model
    deployment, which changes the observed evidence; see ``unobserved_signals``.)
    """
    agent_domain = _agent_domains(sandbox_dir)
    domain_a = _domain_of_a_duplicate(estate, agent_domain)
    domain_b = next(d for d in estate.domain_ids if d != domain_a)
    run_ab, graph, _ = _run(estate, [domain_a, domain_b])
    assert run_ab.candidates
    for c in run_ab.candidates:
        domains = {agent_domain[s.root] for s in c.recommendation.subject_ids}
        assert len(domains) == 1, "a pair never spans two domains"
        assert domains <= {domain_a, domain_b}
        assert c.recommendation.domain_id.root in domains
    assert {agent_domain[r.node_id] for r in graph.requests} <= {domain_a, domain_b}


def test_narrow_scope_marks_hidden_targets_as_unobserved_not_as_mismatch(
    estate: Estate, sandbox_dir: Path
) -> None:
    """Model deployments live in another domain: under a single-domain scope the signal is
    unobserved (GraphQuery cuts the out-of-scope target), never scored as a mismatch."""
    agent_domain = _agent_domains(sandbox_dir)
    domain_a = _domain_of_a_duplicate(estate, agent_domain)
    run, _, _ = _run(estate, [domain_a])
    seen = [
        *(c.breakdown for c in run.candidates),
        *(r.breakdown for r in run.review_candidates),
    ]
    assert seen
    hidden = [b for b in seen if "model_deployment" in b.unobserved_signals]
    assert hidden, "sandbox model deployments are homed outside this domain"
    for b in hidden:
        assert b.shared_model_deployment_ids == ()
        assert b.model_deployment == 0.0
    for c in run.candidates:
        if "model_deployment" in c.breakdown.unobserved_signals:
            assert c.recommendation.coverage.method == "partial"
            assert c.recommendation.uncertainty.upper is not None
            assert c.recommendation.score is not None
            assert c.recommendation.uncertainty.upper >= c.recommendation.score
            assert c.recommendation.coverage.observed_fraction is not None
            assert c.recommendation.coverage.observed_fraction.root < 1.0


def test_scope_with_no_matching_domain_reads_and_yields_nothing(estate: Estate) -> None:
    ghost = "commercial:synthco:sandbox:domain:does-not-exist"
    run, graph, _ = _run(estate, [ghost])
    assert run.candidates == ()
    assert run.review_candidates == ()
    assert run.agents_considered == 0
    assert graph.requests == []


def test_other_customer_scope_yields_nothing(estate: Estate) -> None:
    """Same domain ids, different customer: the repository reports nothing in scope."""
    run, graph, _ = _run(estate, estate.domain_ids[:2], customer="othercorp")
    assert run.candidates == ()
    assert run.agents_considered == 0
    assert graph.requests == []


def test_other_cloud_scope_yields_nothing(estate: Estate) -> None:
    run, graph, _ = _run(estate, estate.domain_ids[:2], cloud="government")
    assert run.candidates == ()
    assert graph.requests == []
