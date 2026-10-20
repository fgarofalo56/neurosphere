"""PRP-16 item 6: one worker entry point from a registered benchmark to stored evaluation data.

Per call, for caller-supplied inputs (registry, judge, capability matrix, budget ledger, store):

1. run the OFFLINE benchmark (``EvaluationService.run_offline``) through the same guard and
   budget as every other run;
2. calibrate each LLM judge that produced scores, per dimension, against the human ``LabelSet``
   (item 3), then re-emit the contract results with those calibrations attached;
3. store, under the item 4 conventions: results (each re-checked with ``check_result_references``),
   calibration reports keyed by ``judge_config_key`` (judge config id = ``judge_model_id``,
   version = ``<model_version>+<prompt_version>``), per-stratum ``SamplingCoverage`` and drift
   alerts;
4. optionally run the ONLINE sampled evaluation over a ``RecordSource`` and store it the same way.

This module reads no clock, no network and no credential, and imports no sandbox module: the
registry, judge and records are injected. Sampling coverage is stored as ``sampled`` = items a judge
actually scored or abstained on, and ``coverage_fraction`` = that count over the stratum population,
so the two numbers always agree (a skipped stratum shows 0 evaluated, never a hidden gap).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.evaluation.calibration import (
    DEFAULT_MIN_LABELS,
    CalibrationReport,
    DriftResult,
    JudgedItem,
    LabelSet,
    calibrate,
    detect_drift,
)
from neurosphere_core.evaluation.judge import Judge
from neurosphere_core.evaluation.registry import (
    Cloud,
    DatasetVersion,
    Dimension,
    EvaluationRegistry,
    JudgeConfig,
    check_result_references,
)
from neurosphere_core.evaluation.store import EvaluationStore, SamplingCoverage

from neurosphere_workers.evaluation.budget import BudgetLedger
from neurosphere_workers.evaluation.models import RunReport
from neurosphere_workers.evaluation.service import (
    EvaluationService,
    OfflineRunConfig,
    OnlineRunConfig,
)
from neurosphere_workers.evaluation.source import RecordSource

__all__ = [
    "CalibrationSettings",
    "DriftCheck",
    "OfflineStage",
    "OnlineStage",
    "PipelineSummary",
    "calibration_store_key",
    "run_pipeline",
]

Metric = Literal["cohen_kappa", "spearman", "accuracy"]


@dataclass(frozen=True, slots=True)
class OfflineStage:
    """A registered benchmark dataset version and the run that scores it."""

    dataset: DatasetVersion
    config: OfflineRunConfig


@dataclass(frozen=True, slots=True)
class OnlineStage:
    """Redacted archive-shaped records and the sampled run over them.

    ``frame`` is the versioned sampling-frame dataset the run cites; it is registered when the
    registry does not hold that version yet.
    """

    source: RecordSource
    config: OnlineRunConfig
    frame: DatasetVersion | None = None


@dataclass(frozen=True, slots=True)
class CalibrationSettings:
    metric: Metric = "cohen_kappa"
    min_labels: int = DEFAULT_MIN_LABELS
    level: float = 0.95
    seed: int = 0


@dataclass(frozen=True, slots=True)
class DriftCheck:
    """Compare a baseline window of judge scores with the current one; an alert is stored.

    ``current`` ``None`` means "the judged items of this pipeline's offline run for ``dimension``".
    """

    cloud: Cloud
    customer_id: str
    domain_id: str
    subject_id: str
    dimension: Dimension
    baseline: tuple[JudgedItem, ...]
    threshold: float
    min_n: int
    current: tuple[JudgedItem, ...] | None = None


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """What one run stored and what it deliberately did not."""

    offline: RunReport
    online: RunReport | None
    calibrations: tuple[CalibrationReport, ...]
    """Registry-keyed reports (judge config id and version), as attached to the results."""
    calibrations_stored: int
    calibration_skipped: tuple[str, ...]
    """LLM judges that produced no scored item, so there was nothing to calibrate."""
    results_stored: int
    coverage_stored: int
    coverage_unattributed: int
    drift: tuple[DriftResult, ...]
    drift_alerts_stored: int
    uncalibrated_judges: tuple[str, ...]
    result_ids: tuple[str, ...] = field(default=())


def calibration_store_key(config: JudgeConfig) -> tuple[str, str] | None:
    """The key item 4 looks a stored report up by (``store.judge_config_key`` of the result's
    judge block): id = ``judge_model_id``, version = ``<model_version>+<prompt_version>``."""
    if (
        config.judge_model_id is None
        or config.judge_model_version is None
        or config.judge_prompt_version is None
    ):
        return None
    return config.judge_model_id, f"{config.judge_model_version}+{config.judge_prompt_version}"


def _calibrate_all(
    report: RunReport,
    judges: Mapping[Dimension, JudgeConfig],
    labels: LabelSet | None,
    settings: CalibrationSettings,
    now: datetime,
) -> tuple[list[CalibrationReport], list[str]]:
    reports: list[CalibrationReport] = []
    skipped: list[str] = []
    if labels is None:
        return reports, skipped
    for dimension, config in sorted(judges.items()):
        if config.judge_kind not in ("llm_judge", "hybrid"):
            continue
        scored = [
            j
            for j in report.judged_items
            if j.dimension == dimension and j.judge_config_id == config.judge_config_id
        ]
        if not scored:
            skipped.append(f"{config.judge_config_id}@{config.version}:{dimension}")
            continue
        reports.append(
            calibrate(
                scored,
                labels,
                dimension=dimension,
                label_set_version=labels.label_set_version,
                metric=settings.metric,
                calibration_ref=f"cal-{report.run_id}-{config.judge_config_id}-{dimension}",
                calibrated_at=now,
                min_labels=settings.min_labels,
                level=settings.level,
                seed=settings.seed,
            )
        )
    return reports, skipped


async def _store_report(
    store: EvaluationStore, registry: EvaluationRegistry, report: RunReport, now: datetime
) -> tuple[list[str], int, int]:
    """Store results and coverage of one run: ``(result ids, coverage stored, unattributed)``."""
    ids: list[str] = []
    for result in report.results:
        check_result_references(result, registry)
        await store.put_result(result)
        ids.append(result.evaluation_id.root)

    homes: dict[str, tuple[str, str]] = {}
    for outcome in report.outcomes:
        if outcome.customer_id and outcome.domain_id:
            homes.setdefault(outcome.stratum, (outcome.customer_id, outcome.domain_id))
    stored = 0
    unattributed = 0
    for cov in report.coverage:
        home = homes.get(cov.stratum)
        if home is None:
            unattributed += 1
            continue
        fraction = None
        if cov.population:
            fraction = min(1.0, cov.evaluated / cov.population)
        await store.put_coverage(
            SamplingCoverage(
                cloud=report.cloud,
                customer_id=home[0],
                domain_id=home[1],
                run_id=report.run_id,
                stratum=cov.stratum,
                sampled=cov.evaluated,
                population=cov.population,
                coverage_fraction=fraction,
                recorded_at=now,
            )
        )
        stored += 1
    return ids, stored, unattributed


async def run_pipeline(
    *,
    registry: EvaluationRegistry,
    judge: Judge,
    matrix: CapabilityMatrix,
    store: EvaluationStore,
    ledger: BudgetLedger,
    clock: Callable[[], datetime],
    offline: OfflineStage,
    labels: LabelSet | None = None,
    online: OnlineStage | None = None,
    drift_checks: Sequence[DriftCheck] = (),
    calibration: CalibrationSettings = CalibrationSettings(),  # noqa: B008 - frozen value object
) -> PipelineSummary:
    """Run, calibrate and store. ``clock`` is the only time source (no wall clock here).

    A budget stop is not an error: the returned reports carry ``budget_exhausted`` and the
    coverage achieved. An LLM judge without a calibrated report emits no result and is listed in
    ``uncalibrated_judges``.
    """
    service = EvaluationService(
        judge=judge, matrix=matrix, registry=registry, ledger=ledger, clock=clock
    )
    now = clock()

    raw = await service.run_offline(offline.dataset, offline.config)
    cal_reports, cal_skipped = _calibrate_all(raw, offline.config.judges, labels, calibration, now)
    offline_report = service.attach_calibrations(raw, cal_reports)

    cloud = offline.config.cloud
    customer = offline.config.customer_id
    domain = offline.config.domain_id
    stored_cals = 0
    configs = {(c.judge_config_id, c.version): c for c in offline.config.judges.values()}
    for rep in cal_reports:
        config = configs.get((rep.judge_config_id or "", rep.judge_config_version or ""))
        key = None if config is None else calibration_store_key(config)
        if key is None:
            continue
        await store.put_calibration(
            cloud,
            customer,
            domain,
            rep.model_copy(update={"judge_config_id": key[0], "judge_config_version": key[1]}),
        )
        stored_cals += 1

    result_ids, cov_stored, unattributed = await _store_report(store, registry, offline_report, now)
    uncalibrated = list(offline_report.uncalibrated_judges)

    online_report: RunReport | None = None
    if online is not None:
        frame = online.frame
        if frame is not None and registry.datasets.get(frame.dataset_id, frame.version) is None:
            registry.datasets.register(frame)
        online_report = await service.run_online(
            online.source, online.config, calibrations=cal_reports
        )
        ids, cov, unat = await _store_report(store, registry, online_report, now)
        result_ids.extend(ids)
        cov_stored += cov
        unattributed += unat
        uncalibrated.extend(j for j in online_report.uncalibrated_judges if j not in uncalibrated)

    drift_results: list[DriftResult] = []
    alerts = 0
    for check in drift_checks:
        window = (
            check.current
            if check.current is not None
            else tuple(j for j in offline_report.judged_items if j.dimension == check.dimension)
        )
        outcome = detect_drift(
            check.baseline,
            window,
            dimension=check.dimension,
            subject_id=check.subject_id,
            threshold=check.threshold,
            min_n=check.min_n,
            detected_at=now,
        )
        drift_results.append(outcome)
        if outcome.alert is not None:
            await store.put_drift_alert(
                check.cloud, check.customer_id, check.domain_id, outcome.alert
            )
            alerts += 1

    return PipelineSummary(
        offline=offline_report,
        online=online_report,
        calibrations=tuple(cal_reports),
        calibrations_stored=stored_cals,
        calibration_skipped=tuple(cal_skipped),
        results_stored=len(result_ids),
        coverage_stored=cov_stored,
        coverage_unattributed=unattributed,
        drift=tuple(drift_results),
        drift_alerts_stored=alerts,
        uncalibrated_judges=tuple(uncalibrated),
        result_ids=tuple(result_ids),
    )
