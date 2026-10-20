"""Online mode: metadata-derivable dimensions only; groundedness is never fabricated."""

from __future__ import annotations

import pytest
from neurosphere_core.evaluation.judge import JudgeRequest, JudgeResponse
from neurosphere_core.evaluation.registry import check_result_references
from neurosphere_workers.evaluation.models import RunReport
from neurosphere_workers.evaluation.source import InMemoryRecordSource

from .support import (
    CountingJudge,
    calibrated_report,
    llm_config,
    make_registry,
    make_service,
    online_config,
    programmatic_config,
    record,
)


def _by_outcome(request: JudgeRequest) -> JudgeResponse:
    ok = request.payload["outcome"] == "success"
    return JudgeResponse(
        value=1.0 if ok else 0.0, abstained=False, input_tokens=90, output_tokens=10
    )


def _records() -> list[dict]:  # type: ignore[type-arg]
    runs = [record(n, outcome="success" if n % 4 else "error") for n in range(1, 21)]
    tools = [record(n, span_kind="tool_call", outcome="success") for n in range(21, 31)]
    return [*runs, *tools]


async def _run(cals: bool) -> tuple[CountingJudge, RunReport]:
    cfg = llm_config()
    judge = CountingJudge(_by_outcome)
    service = make_service(judge, [cfg])
    calibrations = (
        [calibrated_report(cfg, "task_success"), calibrated_report(cfg, "tool_correctness")]
        if cals
        else []
    )
    report = await service.run_online(
        InMemoryRecordSource(_records()), online_config(cfg), calibrations=calibrations
    )
    return judge, report


async def test_task_success_and_tool_correctness_are_scored_from_metadata() -> None:
    judge, report = await _run(cals=True)
    assert {r.dimension for r in judge.calls} == {"task_success", "tool_correctness"}
    # The judge only ever sees a fixed metadata whitelist, never the record.
    for req in judge.calls:
        assert set(req.payload) == {"span_kind", "outcome", "duration_ms", "retry_attempt"}
    assert report.evaluated_total == 30
    assert report.status == "completed"
    assert len(report.judged_items) == 30
    assert len(report.results) == 2


async def test_groundedness_is_null_not_estimable_and_result_is_partial() -> None:
    _, report = await _run(cals=True)
    assert report.limited_dimensions == {"groundedness": "bodies_not_archived"}
    for result in report.results:
        assert result.status == "partial"
        assert result.mode == "online_sampled"
        assert result.cloud == "government"
        assert result.data_handling.boundary_cloud == "government"
        assert result.data_handling.data_state == "redacted"
        grounded = next(s for s in result.scores if s.dimension == "groundedness")
        assert grounded.value is None
        assert grounded.uncertainty.method == "not_estimable"
        assert grounded.sample_size == 0


async def test_binary_scores_carry_a_wilson_interval() -> None:
    _, report = await _run(cals=True)
    task = next(r for r in report.results if r.scores[0].dimension == "task_success")
    score = task.scores[0]
    assert score.sample_size == 20
    assert score.value == pytest.approx(15 / 20)
    assert score.uncertainty.method == "confidence_interval"
    assert score.uncertainty.level == 0.95
    assert score.uncertainty.lower is not None and score.uncertainty.upper is not None
    assert score.uncertainty.lower < 0.75 < score.uncertainty.upper
    assert 0.0 <= score.uncertainty.lower and score.uncertainty.upper <= 1.0
    assert task.sampling.method == "stratified"
    assert task.sampling.population_size is not None
    assert task.sampling.population_size.model_dump() == 20
    assert task.sampling.coverage_fraction is not None
    assert task.sampling.coverage_fraction.root == 1.0
    assert task.judge.judge_kind == "llm_judge"
    assert task.calibration is not None


async def test_uncalibrated_llm_judge_emits_no_result_but_keeps_judged_items() -> None:
    _, report = await _run(cals=False)
    assert report.results == ()
    assert set(report.uncalibrated_judges) == {
        "judge-a@1:task_success",
        "judge-a@1:tool_correctness",
    }
    assert report.unemitted == {"uncalibrated_judge": 2}
    assert len(report.judged_items) == 30  # calibration can still run on them


async def test_calibration_can_be_attached_after_the_run() -> None:
    cfg = llm_config()
    judge = CountingJudge(_by_outcome)
    service = make_service(judge, [cfg])
    report = await service.run_online(InMemoryRecordSource(_records()), online_config(cfg))
    assert report.results == ()
    later = service.attach_calibrations(
        report, [calibrated_report(cfg, "task_success"), calibrated_report(cfg, "tool_correctness")]
    )
    assert len(later.results) == 2
    assert later.uncalibrated_judges == ()
    assert judge.call_count == 30  # re-emitting did not call the judge again


async def test_calibration_for_a_different_judge_version_does_not_count() -> None:
    cfg = llm_config()
    other = calibrated_report(cfg, "task_success").model_copy(update={"judge_config_version": "2"})
    judge = CountingJudge(_by_outcome)
    report = await make_service(judge, [cfg]).run_online(
        InMemoryRecordSource(_records()), online_config(cfg), calibrations=[other]
    )
    assert report.results == ()


async def test_programmatic_judge_needs_no_calibration_and_no_usage() -> None:
    prog = programmatic_config()
    judge = CountingJudge(_by_outcome)
    service = make_service(judge, [prog])
    report = await service.run_online(InMemoryRecordSource(_records()), online_config(prog))
    assert len(report.results) == 2
    for result in report.results:
        assert result.judge.judge_kind == "programmatic"
        assert result.calibration is None
        assert result.evaluator_usage is None
    assert report.usage[0].input_tokens == 30 * 90  # still tracked in the run report


async def test_results_reference_registered_versions() -> None:
    cfg = llm_config()
    _, report = await _run(cals=True)
    registry = make_registry(cfg)
    for result in report.results:
        check_result_references(result, registry)
        assert result.dataset.dataset_id.root == "frame-online"
        assert result.rubric.rubric_version.root == "1"
        assert result.judge.judge_model_version is not None


async def test_records_without_a_resolved_agent_cannot_become_results() -> None:
    cfg = llm_config()
    judge = CountingJudge(_by_outcome)
    recs = [record(n, agent=None) for n in range(1, 6)]
    report = await make_service(judge, [cfg]).run_online(
        InMemoryRecordSource(recs),
        online_config(cfg),
        calibrations=[calibrated_report(cfg, "task_success")],
    )
    assert judge.call_count == 5
    assert report.results == ()
    assert report.unemitted == {"subject_unresolved": 1}
