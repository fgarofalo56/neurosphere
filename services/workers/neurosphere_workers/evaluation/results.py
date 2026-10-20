"""Turn a ``RunReport`` into validated ``EvaluationResult`` contract documents (PRP-16 item 2).

One result per (customer, domain, subject, dimension, judge config). Rules:

- An ``llm_judge``/``hybrid`` result carries a calibration block, so it is emitted only when a
  calibrated ``CalibrationReport`` for that exact judge config version and dimension is supplied;
  otherwise it is NOT emitted and ``uncalibrated_judge`` is recorded (the judged items are still in
  the report so calibration can run). Programmatic judges need no calibration.
- Status is ``partial`` when the run was not completed, any item of the (subject, dimension) was
  skipped, abstained or never evaluated, or the mode is online (groundedness is not estimable from
  an archive without bodies; it appears as a null score with ``not_estimable`` uncertainty).
- Binary dimensions (scale 0..1, every value 0 or 1) get a Wilson interval; other values get a
  normal-approximation interval on the mean, clamped to the rubric scale. No data is ``null``.
- ``data_handling.boundary_cloud`` equals the run cloud; every result is checked against the
  registry (dataset, rubric and judge-config versions must be registered).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.evaluation.calibration import (
    CalibrationReport,
    Interval,
    format_timestamp,
    mean_difference_interval,
    proportion_interval,
    to_contract_calibration,
    to_contract_uncertainty,
)
from neurosphere_core.evaluation.registry import (
    EvaluationRegistryProtocol,
    JudgeConfig,
    check_result_references,
)

from neurosphere_workers.evaluation.models import ItemOutcome, RunReport

__all__ = ["REASON_UNCALIBRATED", "build_results"]

REASON_UNCALIBRATED: Final = "uncalibrated_judge"
REASON_DOMAIN_UNATTRIBUTED: Final = "domain_unattributed"
REASON_SUBJECT_UNRESOLVED: Final = "subject_unresolved"
REASON_NO_JUDGED_ITEMS: Final = "no_items_judged"
_CURRENCY: Final = "USD"
_QUANT: Final = Decimal("0.000000000001")

_GroupKey = tuple[str | None, str | None, str | None, str, str, str]


def _calibration_index(
    calibrations: Iterable[CalibrationReport],
) -> dict[tuple[str, str, str], CalibrationReport]:
    index: dict[tuple[str, str, str], CalibrationReport] = {}
    for rep in calibrations:
        if rep.judge_config_id is not None and rep.judge_config_version is not None:
            index[(rep.judge_config_id, rep.judge_config_version, rep.dimension)] = rep
    return index


def _interval(values: list[float], lo: float, hi: float) -> Interval:
    if not values:
        return Interval.not_estimable()
    if lo == 0.0 and hi == 1.0 and all(v in (0.0, 1.0) for v in values):
        return proportion_interval(sum(1 for v in values if v == 1.0), len(values))
    found = mean_difference_interval(values)
    if found.lower is None or found.upper is None:
        return found
    return found.model_copy(update={"lower": max(lo, found.lower), "upper": min(hi, found.upper)})


def _score(dimension: str, outcomes: list[ItemOutcome], lo: float, hi: float) -> dict[str, Any]:
    values = [float(o.value) for o in outcomes if o.status == "scored" and o.value is not None]
    abstained = sum(1 for o in outcomes if o.status == "abstained")
    mean = (sum(values) / len(values)) if values else None
    return {
        "dimension": dimension,
        "value": mean,
        "scale": {"min": lo, "max": hi},
        "uncertainty": to_contract_uncertainty(_interval(values, lo, hi)).model_dump(mode="json"),
        "sample_size": len(values),
        "abstained_count": abstained,
    }


def _judge_block(config: JudgeConfig) -> dict[str, Any]:
    if config.judge_kind == "programmatic":
        return {"judge_kind": "programmatic", "program_version": config.program_version}
    return {
        "judge_kind": config.judge_kind,
        "judge_model_id": config.judge_model_id,
        "judge_model_version": config.judge_model_version,
        "judge_prompt_version": config.judge_prompt_version,
    }


def _window(group: list[ItemOutcome], report: RunReport) -> dict[str, str]:
    times: list[datetime] = [o.event_time for o in group if o.event_time is not None]
    start = min(times) if times else report.started_at
    end = max(times) if times else report.completed_at
    if end <= start:
        end = start + timedelta(seconds=1)
    return {"start": format_timestamp(start), "end": format_timestamp(end)}


def _usage(group: list[ItemOutcome], config: JudgeConfig) -> dict[str, Any] | None:
    if config.judge_kind == "programmatic":
        return None
    used = [o for o in group if o.input_tokens is not None]
    cost = sum((o.cost or Decimal(0) for o in used), Decimal(0)).quantize(_QUANT)
    return {
        "judge_input_tokens": sum(o.input_tokens or 0 for o in used),
        "judge_output_tokens": sum(o.output_tokens or 0 for o in used),
        "estimated_cost": {
            "amount": format(cost, "f"),
            "currency": _CURRENCY,
            "price_version": config.price_version,
        },
    }


def build_results(
    report: RunReport,
    *,
    calibrations: Iterable[CalibrationReport] = (),
    registry: EvaluationRegistryProtocol,
) -> tuple[tuple[EvaluationResult, ...], tuple[str, ...], dict[str, int]]:
    """``(results, uncalibrated judges, unemitted counts by reason)``."""
    index = _calibration_index(calibrations)
    configs: Mapping[tuple[str, str], JudgeConfig] = {
        (c.judge_config_id, c.version): c for c in report.judge_configs
    }
    populations = {
        (p.customer_id, p.domain_id, p.subject_id, p.dimension): p.population
        for p in report.group_populations
    }
    by_subject: dict[tuple[str | None, str | None, str | None, str], list[ItemOutcome]] = (
        defaultdict(list)
    )
    groups: dict[_GroupKey, list[ItemOutcome]] = defaultdict(list)
    for o in report.outcomes:
        by_subject[(o.customer_id, o.domain_id, o.subject_id, o.dimension)].append(o)
        if o.judge_config_id is not None and o.judge_config_version is not None:
            key = (
                o.customer_id,
                o.domain_id,
                o.subject_id,
                o.dimension,
                o.judge_config_id,
                o.judge_config_version,
            )
            groups[key].append(o)

    results: list[EvaluationResult] = []
    uncalibrated: list[str] = []
    unemitted: dict[str, int] = defaultdict(int)
    lo, hi = report.rubric.scale_min, report.rubric.scale_max

    for key in sorted(groups, key=lambda k: tuple("" if p is None else p for p in k)):
        customer, domain_id, subject_id, dimension, config_id, config_version = key
        group = groups[key]
        config = configs[(config_id, config_version)]
        judged = [o for o in group if o.status in ("scored", "abstained")]
        if customer is None or domain_id is None:
            unemitted[REASON_DOMAIN_UNATTRIBUTED] += 1
            continue
        if subject_id is None:
            unemitted[REASON_SUBJECT_UNRESOLVED] += 1
            continue
        if not judged:
            unemitted[REASON_NO_JUDGED_ITEMS] += 1
            continue
        calibration = None
        if config.judge_kind in ("llm_judge", "hybrid"):
            cal_report = index.get((config_id, config_version, dimension))
            calibration = None if cal_report is None else to_contract_calibration(cal_report)
            if calibration is None:
                label = f"{config_id}@{config_version}:{dimension}"
                if label not in uncalibrated:
                    uncalibrated.append(label)
                unemitted[REASON_UNCALIBRATED] += 1
                continue

        scores = [_score(dimension, group, lo, hi)]
        if report.mode == "online_sampled":  # D2: never fabricated, null + not_estimable
            scores.append(
                {
                    "dimension": "groundedness",
                    "value": None,
                    "scale": {"min": lo, "max": hi},
                    "uncertainty": {"method": "not_estimable"},
                    "sample_size": 0,
                    "abstained_count": None,
                }
            )
        subject_all = by_subject[(customer, domain_id, subject_id, dimension)]
        complete = report.status == "completed" and all(o.status == "scored" for o in subject_all)
        population = populations.get((customer, domain_id, subject_id, dimension))
        sample_size = len(judged)
        digest = hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:12]
        document: dict[str, Any] = {
            "schema_version": "1.0.0",
            "evaluation_id": f"{report.run_id}.{digest}",
            "cloud": report.cloud,
            "customer_id": customer,
            "domain_id": domain_id,
            "subject_id": subject_id,
            "mode": report.mode,
            "status": "completed" if complete and report.mode == "offline_benchmark" else "partial",
            "dataset": {"dataset_id": report.dataset_id, "dataset_version": report.dataset_version},
            "rubric": {
                "rubric_id": report.rubric.rubric_id,
                "rubric_version": report.rubric.version,
            },
            "judge": _judge_block(config),
            "scores": scores,
            "sampling": {
                "method": "stratified" if report.mode == "online_sampled" else "full",
                "rate": report.rate if report.mode == "online_sampled" else None,
                "sample_size": sample_size,
                "population_size": population,
                "coverage_fraction": (min(1.0, sample_size / population) if population else None),
                "window": _window(group, report),
            },
            "calibration": (None if calibration is None else calibration.model_dump(mode="json")),
            "data_handling": {"data_state": report.data_state, "boundary_cloud": report.cloud},
            "evaluator_usage": _usage(group, config),
            "started_at": format_timestamp(report.started_at),
            "completed_at": format_timestamp(report.completed_at),
        }
        result = EvaluationResult.model_validate(document)
        check_result_references(result, registry)
        results.append(result)
    return tuple(results), tuple(uncalibrated), dict(unemitted)
