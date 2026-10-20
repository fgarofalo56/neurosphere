"""Harness for evaluation API tests: PRP-06 authz harness (dev-issuer tokens, in-memory policy
store), the real router and an in-memory evaluation store. No network.

ALICE views FINANCE, BOB views OPERATIONS. ``services/api/tests/evaluation`` has no
``__init__.py`` (a sibling ``evaluation`` test package exists under packages/core): import by
module name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.evaluation import PREFIX, build_router
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.auth.scope import Role
from neurosphere_core.evaluation.calibration import (
    BiasEstimate,
    CalibrationReport,
    Interval,
    StratumCoverage,
)
from neurosphere_core.evaluation.store import InMemoryEvaluationStore

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
EXAMPLES = (
    Path(__file__).resolve().parents[4] / "packages/contracts/schemas/evaluation/v1/examples/valid"
)
JUDGE_MODEL = "commercial:contoso:foundry:model_deployment:judge-eastus"
JUDGE_CONFIG = (JUDGE_MODEL, "2026-08-01+7")
T = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def make_result(n: int, *, domain: str = FINANCE, **overrides: Any) -> EvaluationResult:
    doc = json.loads((EXAMPLES / "evaluation-result.offline-llm-judge.json").read_text("utf-8"))
    doc["evaluation_id"] = f"eval:r-{n:04d}"
    doc["domain_id"] = domain
    doc.update(overrides)
    return EvaluationResult.model_validate(doc)


def score(
    dimension: str,
    value: float | None,
    sample_size: int,
    bounds: tuple[float, float] | None = None,
) -> dict[str, Any]:
    uncertainty: dict[str, Any] = {"method": "not_estimable"}
    if value is not None and bounds is not None:
        uncertainty = {
            "method": "confidence_interval",
            "lower": bounds[0],
            "upper": bounds[1],
            "level": 0.95,
        }
    return {
        "dimension": dimension,
        "value": value,
        "scale": {"min": 0, "max": 1},
        "uncertainty": uncertainty,
        "sample_size": sample_size,
    }


def make_report(
    dimension: str = "groundedness",
    *,
    state: str = "calibrated",
    judged: int = 10,
    labelled: int = 6,
) -> CalibrationReport:
    cov = StratumCoverage(
        stratum="all",
        judged=judged,
        labelled=labelled,
        missing=judged - labelled,
        label_fraction=labelled / judged,
    )
    return CalibrationReport(
        calibration_ref="cal:1",
        dimension=dimension,  # type: ignore[arg-type]
        judge_config_id=JUDGE_CONFIG[0],
        judge_config_version=JUDGE_CONFIG[1],
        label_set_version="labels-1",
        calibrated_at=T,
        state=state,  # type: ignore[arg-type]
        uncalibrated_reason=None,
        metric="accuracy",
        agreement=0.9,
        agreement_sample_size=labelled,
        agreement_interval=Interval.not_estimable(),
        bias=BiasEstimate(mean_difference=None, interval=Interval.not_estimable(), sample_size=0),
        bias_checks=(),
        coverage=(cov,),
        overall_coverage=cov,
        min_labels=1,
    )


@dataclass
class Api:
    h: Any
    store: InMemoryEvaluationStore

    def get(self, who: str | None, path: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=headers)


def make_api(
    *results: EvaluationResult, wire: bool = True, pilot: tuple[str, ...] | None = None
) -> Api:
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    store = InMemoryEvaluationStore(results)
    if wire:
        h.app.state.evaluation_store = store
    if pilot is not None:
        h.app.state.evaluation_pilot_dataset_ids = pilot
    return Api(h=h, store=store)
