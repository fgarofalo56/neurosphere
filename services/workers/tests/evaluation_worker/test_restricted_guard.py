"""Restricted-content guard: the real guard path runs; the judge double must see zero calls."""

from __future__ import annotations

import pytest
from neurosphere_core.capabilities import load_matrix
from neurosphere_workers.evaluation.guard import check_candidate
from neurosphere_workers.evaluation.models import (
    REASON_BODY_FIELDS,
    REASON_JUDGE_CLOUD_MISMATCH,
    REASON_JUDGE_NOT_APPROVED,
    REASON_JUDGE_UNAVAILABLE,
    REASON_PRICE_UNKNOWN,
    Candidate,
)
from neurosphere_workers.evaluation.source import InMemoryRecordSource

from .support import (
    GOV_DOWN_ROW,
    CountingJudge,
    commercial_matrix,
    llm_config,
    make_service,
    online_config,
    record,
)


async def _run_one(item: dict, *, cloud: str = "government", judge_cfg=None, matrix=None):  # type: ignore[no-untyped-def]
    cfg = judge_cfg or llm_config(cloud)
    judge = CountingJudge()
    service = make_service(judge, [cfg], matrix=matrix)
    report = await service.run_online(InMemoryRecordSource([item]), online_config(cfg, cloud=cloud))
    return judge, report


@pytest.mark.parametrize("classification", ["restricted", None, "top-secret", ""])
async def test_restricted_and_unknown_classification_never_reach_the_judge(
    classification: str | None,
) -> None:
    judge, report = await _run_one(record(1, classification=classification))
    assert judge.call_count == 0
    assert report.skip_counts == {REASON_JUDGE_NOT_APPROVED: 1}
    (outcome,) = report.outcomes
    assert outcome.status == "skipped"
    assert outcome.reason == REASON_JUDGE_NOT_APPROVED
    assert outcome.detail is not None
    assert "restricted" in outcome.detail  # null/unknown fails closed to restricted
    assert report.evaluated_total == 0
    assert report.judged_items == ()
    assert report.results == ()


async def test_cui_never_goes_to_a_commercial_judge() -> None:
    # Commercial run, commercial judge approved only for public/internal: cui is refused.
    judge, report = await _run_one(
        record(1, classification="cui", cloud="commercial"),
        cloud="commercial",
        judge_cfg=llm_config("commercial", approved=("public", "internal")),
        matrix=commercial_matrix(),
    )
    assert judge.call_count == 0
    assert report.skip_counts == {REASON_JUDGE_NOT_APPROVED: 1}

    # Positive control on the same commercial setup: a public item does get judged.
    judge, report = await _run_one(
        record(2, classification="public", cloud="commercial"),
        cloud="commercial",
        judge_cfg=llm_config("commercial", approved=("public", "internal")),
        matrix=commercial_matrix(),
    )
    assert judge.call_count == 1


async def test_government_run_never_uses_a_commercial_judge() -> None:
    commercial = llm_config("commercial")
    judge, report = await _run_one(
        record(1, classification="public"),
        cloud="government",
        judge_cfg=commercial,
        matrix=commercial_matrix(),
    )
    assert judge.call_count == 0
    assert report.skip_counts == {REASON_JUDGE_CLOUD_MISMATCH: 1}


async def test_unavailable_judge_is_skipped_with_reason() -> None:
    down = llm_config("government", row=GOV_DOWN_ROW)
    judge, report = await _run_one(record(1, classification="public"), judge_cfg=down)
    assert judge.call_count == 0
    assert report.skip_counts == {REASON_JUDGE_UNAVAILABLE: 1}


async def test_body_fields_are_never_transmitted() -> None:
    dirty = record(1, classification="public", extra={"prompt": "do not send"})
    judge, report = await _run_one(dirty)
    assert judge.call_count == 0
    assert report.skip_counts == {REASON_BODY_FIELDS: 1}
    assert "do not send" not in report.model_dump_json()


async def test_approved_items_do_reach_the_judge_and_only_those() -> None:
    cfg = llm_config()
    judge = CountingJudge()
    service = make_service(judge, [cfg])
    items = [
        record(1, classification="public"),
        record(2, classification="internal"),
        record(3, classification="cui"),
        record(4, classification="restricted"),
        record(5, classification=None),
        record(6, classification="mystery"),
    ]
    report = await service.run_online(InMemoryRecordSource(items), online_config(cfg))
    assert judge.call_count == 3
    assert {r.classification for r in judge.calls} == {"public", "internal", "cui"}
    assert report.skip_counts == {REASON_JUDGE_NOT_APPROVED: 3}
    assert report.evaluated_total == 3
    assert report.status == "partial"


def test_guard_checks_the_payload_actually_sent() -> None:
    cand = Candidate(
        item_id="x1",
        classification="public",
        dimension="task_success",
        payload={"outcome": "success", "response": "leak"},
    )
    cfg = llm_config()
    decision = check_candidate(
        cand, judges={"task_success": cfg}, matrix=load_matrix(), cloud="government"
    )
    assert not decision.allowed
    assert decision.reason == REASON_BODY_FIELDS


def test_unknown_price_fails_closed() -> None:
    cfg = llm_config().model_copy(update={"output_price_per_1k_tokens": None})
    cand = Candidate(
        item_id="x1", classification="public", dimension="task_success", payload={"a": 1}
    )
    decision = check_candidate(
        cand, judges={"task_success": cfg}, matrix=load_matrix(), cloud="government"
    )
    assert decision.reason == REASON_PRICE_UNKNOWN
