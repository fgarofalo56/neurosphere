"""Pipeline: rules + duplicates + right-sizing projections into a RecommendationStore.

Synthetic sandbox (fixed seed), the SYNTHETIC sandbox price snapshot, in-memory stores, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from neurosphere_core.pricing import InMemoryPriceSnapshotStore
from neurosphere_core.recommendations import InMemoryRecommendationStore

from neurosphere_workers.recommendations.pipeline import PipelineSummary, run_pipeline
from neurosphere_workers.recommendations.tests.support import (
    CREATED_AT,
    PAIRS,
    SNAPSHOT_ID,
    generate_sandbox,
    make_scope,
    synthetic_prices,
)

SEED = 3


@pytest.fixture(scope="module")
def sandbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pipeline-sandbox")
    generate_sandbox(out, seed=SEED)
    return out


def _domains(directory: Path) -> list[str]:
    lines = (directory / "domains.ndjson").read_text(encoding="utf-8").splitlines()
    return sorted(json.loads(line)["id"] for line in lines if line)


def _manifest(directory: Path) -> dict[str, set[str]]:
    data = json.loads((directory / "anomaly-manifest.json").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for anomaly in data["anomalies"]:
        out.setdefault(anomaly["type"], set()).update(anomaly["affected_ids"])
    return out


@pytest.fixture(scope="module")
async def full_run(sandbox_dir: Path) -> tuple[PipelineSummary, InMemoryRecommendationStore]:
    store = InMemoryRecommendationStore()
    summary = await run_pipeline(
        sandbox_dir,
        scope=make_scope(_domains(sandbox_dir)),
        store=store,
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=CREATED_AT,
    )
    return summary, store


async def _all(store: InMemoryRecommendationStore, domains: list[str], scope_domains: list[str]):  # type: ignore[no-untyped-def]
    scope = make_scope(scope_domains)
    found = []
    for domain in domains:
        cursor = None
        while True:
            page = await store.list(scope, domain, cursor=cursor, limit=200)
            found.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
    return found


async def test_all_three_producers_store_records(
    full_run: tuple[PipelineSummary, InMemoryRecommendationStore], sandbox_dir: Path
) -> None:
    summary, store = full_run
    kinds = summary.counts_by_kind
    assert kinds.get("cost_spike", 0) >= 1
    assert kinds.get("unused_agent", 0) >= 1
    assert kinds.get("candidate_duplicate", 0) >= 1
    assert kinds.get("model_right_sizing", 0) >= 1
    assert summary.stored == sum(kinds.values()) == len(summary.stored_ids)
    domains = _domains(sandbox_dir)
    stored = await _all(store, domains, domains)
    assert len(stored) == summary.stored


async def test_injected_anomalies_are_stored(
    full_run: tuple[PipelineSummary, InMemoryRecommendationStore], sandbox_dir: Path
) -> None:
    _, store = full_run
    domains = _domains(sandbox_dir)
    stored = await _all(store, domains, domains)
    manifest = _manifest(sandbox_dir)
    for kind, anomaly in (
        ("cost_spike", "cost_spike"),
        ("unused_agent", "unused_agent"),
        ("latency_degradation", "latency_regression"),
    ):
        subjects = {s.root for r in stored if r.kind == kind for s in r.subject_ids}
        assert manifest[anomaly] <= subjects, (kind, manifest[anomaly] - subjects)


async def test_every_projection_cites_the_synthetic_price_version(
    full_run: tuple[PipelineSummary, InMemoryRecommendationStore], sandbox_dir: Path
) -> None:
    _, store = full_run
    domains = _domains(sandbox_dir)
    stored = await _all(store, domains, domains)
    projections = [r for r in stored if r.kind == "model_right_sizing"]
    assert projections
    for rec in projections:
        assert rec.advisory is True
        assert rec.projected_estimate is not None
        assert rec.projected_estimate.price_version.root == SNAPSHOT_ID
        assert rec.projected_estimate.price_effective_date is not None


async def test_unresolvable_price_is_skipped_and_reported_never_emitted(
    sandbox_dir: Path,
) -> None:
    store = InMemoryRecommendationStore()
    summary = await run_pipeline(
        sandbox_dir,
        scope=make_scope(_domains(sandbox_dir)),
        store=store,
        prices=InMemoryPriceSnapshotStore(),  # no snapshot at all
        pairs=PAIRS,
        created_at=CREATED_AT,
    )
    assert summary.counts_by_kind.get("model_right_sizing", 0) == 0
    assert summary.skipped_projections
    assert {s.reason for s in summary.skipped_projections} == {"price_unresolved"}
    domains = _domains(sandbox_dir)
    stored = await _all(store, domains, domains)
    assert not [r for r in stored if r.kind == "model_right_sizing"]
    # Rules and duplicates are unaffected by the missing prices.
    assert summary.counts_by_kind.get("cost_spike", 0) >= 1


async def test_candidate_model_missing_from_the_sheet_is_skipped(sandbox_dir: Path) -> None:
    summary = await run_pipeline(
        sandbox_dir,
        scope=make_scope(_domains(sandbox_dir)),
        store=InMemoryRecommendationStore(),
        prices=synthetic_prices(models=("gpt-4.1", "gpt-4.1-nano")),  # no gpt-4.1-mini rows
        pairs=PAIRS,
        created_at=CREATED_AT,
    )
    reasons = {(s.pair_id, s.reason) for s in summary.skipped_projections}
    assert ("large-to-mini", "price_unresolved") in reasons


async def test_scope_limits_what_is_read_and_stored(sandbox_dir: Path) -> None:
    domains = _domains(sandbox_dir)
    only = [domains[0]]
    store = InMemoryRecommendationStore()
    summary = await run_pipeline(
        sandbox_dir,
        scope=make_scope(only),
        store=store,
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=CREATED_AT,
    )
    assert summary.stored > 0
    everything = await _all(
        store, domains, domains
    )  # a wide caller: still only domain A holds data
    assert {r.domain_id.root for r in everything} == set(only)


async def test_other_customer_scope_stores_nothing(sandbox_dir: Path) -> None:
    store = InMemoryRecommendationStore()
    summary = await run_pipeline(
        sandbox_dir,
        scope=make_scope(_domains(sandbox_dir), customer="someone-else"),
        store=store,
        prices=synthetic_prices(),
        pairs=PAIRS,
        created_at=CREATED_AT,
    )
    assert summary.stored == 0


async def test_same_inputs_produce_the_same_records(sandbox_dir: Path) -> None:
    runs = []
    for _ in range(2):
        runs.append(
            await run_pipeline(
                sandbox_dir,
                scope=make_scope(_domains(sandbox_dir)),
                store=InMemoryRecommendationStore(),
                prices=synthetic_prices(),
                pairs=PAIRS,
                created_at=CREATED_AT,
            )
        )
    first, second = runs
    assert first.stored_ids == second.stored_ids
    assert first.counts_by_kind == second.counts_by_kind


async def test_review_candidates_are_reported_not_stored(
    full_run: tuple[PipelineSummary, InMemoryRecommendationStore], sandbox_dir: Path
) -> None:
    summary, store = full_run
    domains = _domains(sandbox_dir)
    stored = await _all(store, domains, domains)
    stored_pairs = {
        frozenset(s.root for s in r.subject_ids) for r in stored if r.kind == "candidate_duplicate"
    }
    for candidate in summary.review_candidates:
        assert frozenset(candidate.subject_ids) not in stored_pairs
