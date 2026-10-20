"""Stratified sampling: per-stratum coverage, determinism by seed, fail-closed strata."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_workers.evaluation.online import candidate_from_record
from neurosphere_workers.evaluation.sampling import stratified_sample
from neurosphere_workers.evaluation.source import InMemoryRecordSource, NdjsonRecordSource

from .support import CountingJudge, llm_config, make_service, online_config, population, record


def _candidates(records: list[dict]) -> list:  # type: ignore[type-arg]
    out = []
    for rec in records:
        cand, _ = candidate_from_record(rec, "government")
        assert cand is not None
        out.append(cand)
    return out


def test_every_stratum_is_covered_at_the_requested_rate() -> None:
    cands = _candidates(population(classifications=("public", "internal", None), per_stratum=10))
    result = stratified_sample(cands, rate=0.25, seed=1)
    assert len(result.strata) == 2 * 2 * 3
    for s in result.strata:
        assert s.population == 10
        assert s.sampled == math.ceil(0.25 * 10) == 3
        assert s.fraction == pytest.approx(0.3)
    assert len(result.selected) == sum(s.sampled for s in result.strata)
    # null classification is its own (restricted) stratum, never merged into another.
    assert any(s.stratum.endswith("/restricted") for s in result.strata)


def test_small_strata_still_get_one_item() -> None:
    cands = _candidates(population(per_stratum=2))
    result = stratified_sample(cands, rate=0.01, seed=1)
    assert all(s.sampled == 1 for s in result.strata)


def test_same_seed_same_sample_different_seed_differs() -> None:
    cands = _candidates(population(per_stratum=20))
    a = stratified_sample(cands, rate=0.3, seed=42)
    b = stratified_sample(list(reversed(cands)), rate=0.3, seed=42)  # input order is irrelevant
    c = stratified_sample(cands, rate=0.3, seed=43)
    assert [x.item_id for x in a.selected] == [x.item_id for x in b.selected]
    assert a.strata == b.strata
    assert {x.item_id for x in a.selected} != {x.item_id for x in c.selected}


def test_selection_is_interleaved_across_strata() -> None:
    cands = _candidates(population(per_stratum=6))
    result = stratified_sample(cands, rate=0.5, seed=3)
    first_round = [x.stratum for x in result.selected[: len(result.strata)]]
    assert len(set(first_round)) == len(result.strata)


def test_duplicates_are_counted_once() -> None:
    recs = population(per_stratum=3)
    cands = _candidates(recs + recs)
    result = stratified_sample(cands, rate=1.0, seed=1)
    assert len(result.selected) == len(recs)


@pytest.mark.parametrize("rate", [0.0, -0.1, 1.5])
def test_invalid_rate_is_rejected(rate: float) -> None:
    with pytest.raises(InvalidSchemaError):
        stratified_sample([], rate=rate, seed=1)


async def test_report_carries_per_stratum_coverage_and_replays_by_seed() -> None:
    cfg = llm_config()
    records = population(classifications=("public", "internal"), per_stratum=10)

    async def run(seed: int, run_id: str):  # type: ignore[no-untyped-def]
        judge = CountingJudge()
        service = make_service(judge, [cfg])
        report = await service.run_online(
            InMemoryRecordSource(records), online_config(cfg, rate=0.3, seed=seed, run_id=run_id)
        )
        return report, [r.item_id for r in judge.calls]

    first, first_ids = await run(5, "run-a")
    _again, again_ids = await run(5, "run-b")
    _other, other_ids = await run(6, "run-c")

    assert first_ids == again_ids
    assert sorted(first_ids) != sorted(other_ids)
    assert first.population_total == len(records)
    assert first.sampled_total == sum(c.sampled for c in first.coverage) == len(first_ids)
    assert len(first.coverage) == 8
    for c in first.coverage:
        assert c.population == 10
        assert c.sampled == 3
        assert c.evaluated == 3
        assert c.sampled_fraction == pytest.approx(0.3)
        assert c.evaluated_fraction == pytest.approx(0.3)
    assert first.status == "completed"
    assert first.seed == 5
    assert first.rate == 0.3


async def test_ndjson_source_gives_the_same_sample_as_memory(tmp_path: Path) -> None:
    cfg = llm_config()
    records = population(per_stratum=5)
    path = tmp_path / "archive.ndjson"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n\n", encoding="utf-8")

    mem_judge, file_judge = CountingJudge(), CountingJudge()
    await make_service(mem_judge, [cfg]).run_online(
        InMemoryRecordSource(records), online_config(cfg, rate=0.4)
    )
    await make_service(file_judge, [cfg]).run_online(
        NdjsonRecordSource(path), online_config(cfg, rate=0.4)
    )
    assert [r.item_id for r in mem_judge.calls] == [r.item_id for r in file_judge.calls]


async def test_malformed_ndjson_line_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.ndjson"
    path.write_text('{"ok": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(InvalidSchemaError):
        async for _ in NdjsonRecordSource(path).records():
            pass


async def test_unscorable_and_cross_cloud_records_are_excluded_not_sampled() -> None:
    cfg = llm_config()
    records = [
        record(1),
        record(2, span_kind="model_call"),
        record(3, cloud="commercial"),
    ]
    judge = CountingJudge()
    report = await make_service(judge, [cfg]).run_online(
        InMemoryRecordSource(records), online_config(cfg)
    )
    assert report.excluded_counts == {"not_scorable_span": 1, "cloud_mismatch": 1}
    assert report.population_total == 1
    assert judge.call_count == 1
