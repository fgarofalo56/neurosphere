"""Offline mode: the sandbox groundedness pilot set through the same guards, recorded fixtures."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import HumanLabelRecord, calibrate, ingest_labels
from neurosphere_core.evaluation.registry import DatasetVersion, EvaluationRegistry, JudgeConfig

# ``sandbox`` lives at the repo root; make this module importable when run on its own.
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from neurosphere_workers.evaluation.budget import BudgetLimits  # noqa: E402
from neurosphere_workers.evaluation.service import (  # noqa: E402
    EvaluationService,
    OfflineRunConfig,
)

from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    PILOT_VERSION,
    load_fixture_judge,
    load_human_labels,
    load_registry,
)

from .support import T0, ledger  # noqa: E402

DOMAIN = "government:sandbox:neurosphere:domain:sbx-dom"
SUBJECT = "government:sandbox:foundry:agent:sbx-agent"


def _setup() -> tuple[EvaluationRegistry, DatasetVersion, JudgeConfig, JudgeConfig]:
    registry = load_registry()
    pilot = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    gov = registry.judge_configs.latest("sbx-judge-government")
    comm = registry.judge_configs.latest("sbx-judge-commercial")
    assert pilot is not None and gov is not None and comm is not None
    return registry, pilot, gov, comm


def _config(judge: JudgeConfig, cloud: str = "government") -> OfflineRunConfig:
    registry = load_registry()
    rubric = registry.rubrics.latest("sbx-rubric")
    assert rubric is not None
    return OfflineRunConfig(
        run_id="off-1",
        cloud=cloud,  # type: ignore[arg-type]
        rubric=rubric,
        judges={"groundedness": judge},
        customer_id="sandbox",
        domain_id=DOMAIN,
        subject_id=SUBJECT,
    )


def _service(registry: EvaluationRegistry, judge, led=None) -> EvaluationService:  # type: ignore[no-untyped-def]
    return EvaluationService(
        judge=judge,
        matrix=load_matrix(),
        registry=registry,
        ledger=led or ledger(),
        clock=lambda: T0,
    )


async def test_pilot_set_runs_with_recorded_fixtures_and_skips_restricted() -> None:
    registry, pilot, gov, _ = _setup()
    judge = load_fixture_judge()
    report = await _service(registry, judge).run_offline(pilot, _config(gov))

    restricted = sum(1 for i in pilot.items if i.classification == "restricted")
    assert restricted == 8
    assert report.skip_counts == {"judge_not_approved": restricted}
    assert judge.call_count == len(pilot.items) - restricted == 42
    assert {r.classification for r in judge.calls} <= {"public", "internal", "cui"}
    assert report.mode == "offline_benchmark"
    assert report.data_state == "synthetic"
    assert report.status == "partial"
    assert report.population_total == 50
    # Coverage per (dataset, dimension, classification) stratum.
    assert {c.stratum.rsplit("/", 1)[-1] for c in report.coverage} == {
        "public",
        "internal",
        "cui",
        "restricted",
    }
    restricted_cov = next(c for c in report.coverage if c.stratum.endswith("/restricted"))
    assert restricted_cov.evaluated == 0 and restricted_cov.skipped == 8


async def test_commercial_judge_is_disabled_by_the_matrix_and_never_called() -> None:
    registry, pilot, _, comm = _setup()
    judge = load_fixture_judge()
    report = await _service(registry, judge).run_offline(pilot, _config(comm, "commercial"))
    assert judge.call_count == 0
    assert report.skip_counts == {"judge_unavailable": 50}


async def test_government_run_with_commercial_config_is_refused_per_item() -> None:
    registry, pilot, _, comm = _setup()
    judge = load_fixture_judge()
    report = await _service(registry, judge).run_offline(pilot, _config(comm, "government"))
    assert judge.call_count == 0
    assert report.skip_counts == {"judge_cloud_mismatch": 50}


async def test_offline_result_after_calibration_reports_pilot_rate_with_interval() -> None:
    registry, pilot, gov, _ = _setup()
    judge = load_fixture_judge()
    service = _service(registry, judge)
    report = await service.run_offline(pilot, _config(gov))
    assert report.results == ()  # llm judge, not calibrated yet
    assert report.uncalibrated_judges == ("sbx-judge-government@1.0.0:groundedness",)

    human = load_human_labels()
    labels = ingest_labels(
        HumanLabelRecord(
            item_id=lab.item_id,
            dimension="groundedness",
            label_set_version=human.version,
            value=lab.value,
            labeler=lab.labeller,
            labelled_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
        for lab in human.labels
    )
    calibration = calibrate(
        list(report.judged_items),
        labels,
        dimension="groundedness",
        label_set_version=human.version,
        metric="accuracy",
        calibration_ref="cal-pilot-1",
        calibrated_at=T0,
    )
    assert calibration.state == "calibrated"
    final = service.attach_calibrations(report, [calibration])
    (result,) = final.results
    assert result.mode == "offline_benchmark"
    assert result.status == "partial"  # restricted items were skipped, abstentions exist
    assert result.sampling.method == "full"
    assert (
        result.sampling.population_size is not None
        and result.sampling.population_size.model_dump() == 50
    )
    score = result.scores[0]
    assert score.dimension == "groundedness"
    assert score.value is not None and score.sample_size > 0
    assert score.uncertainty.method == "confidence_interval"
    assert score.uncertainty.lower is not None and score.uncertainty.upper is not None
    assert score.uncertainty.lower < score.value < score.uncertainty.upper
    assert result.calibration is not None
    assert result.data_handling.data_state == "synthetic"
    assert result.evaluator_usage is not None
    assert result.evaluator_usage.estimated_cost is not None
    assert result.evaluator_usage.estimated_cost.price_version.root == "sandbox-prices-1"
    assert Decimal(result.evaluator_usage.estimated_cost.amount.root) > 0


async def test_offline_budget_applies_the_same_way() -> None:
    registry, pilot, gov, _ = _setup()
    judge = load_fixture_judge()
    led = ledger(run=BudgetLimits(tokens=2500, cost=Decimal("100")))
    report = await _service(registry, judge, led).run_offline(pilot, _config(gov))
    assert report.status == "budget_exhausted"
    assert 0 < judge.call_count < 42
    assert led.run_consumed[0] <= 2500
    assert report.unevaluated_total > 0


async def test_unregistered_dataset_or_modified_copy_is_rejected() -> None:
    registry, pilot, gov, _ = _setup()
    service = _service(registry, load_fixture_judge())
    tampered = pilot.model_copy(update={"version": "9.9.9"})
    with pytest.raises(InvalidSchemaError):
        await service.run_offline(tampered, _config(gov))
