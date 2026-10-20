"""Test support for the sampling worker: a counting judge double, configs, records, services.

The judge double implements the real ``Judge`` protocol and records every request. It never
touches the network. The guard, ledger, sampler and service under test are the real code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.capabilities import CapabilityMatrix, load_matrix, matrix_from_rows
from neurosphere_core.evaluation.calibration import (
    BiasCheckResult,
    BiasEstimate,
    CalibrationReport,
    Interval,
    StratumCoverage,
)
from neurosphere_core.evaluation.judge import JudgeRequest, JudgeResponse
from neurosphere_core.evaluation.registry import (
    Criterion,
    DatasetItem,
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
)
from neurosphere_workers.evaluation.budget import BudgetLedger, BudgetLimits
from neurosphere_workers.evaluation.service import EvaluationService, OnlineRunConfig

GOV_ROW = "foundry.model_gpt_4_1.government.usgovvirginia.data-zone-standard"
GOV_DOWN_ROW = "foundry.model_gpt_5_1.government.usgovvirginia.regional-standard"
COMM_ROW = "foundry.base.commercial.global.any"
T0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
CUSTOMER = "cust1"
FRAME_ID = "frame-online"
FRAME_VERSION = "1"
RUBRIC_ID = "rubric-online"
RUBRIC_VERSION = "1"

HUGE = BudgetLimits(tokens=10_000_000, cost=Decimal("1000000"))


class CountingJudge:
    """Implements ``Judge``; ``respond`` maps a request to a response (default: score 1.0)."""

    def __init__(
        self,
        respond: Callable[[JudgeRequest], JudgeResponse] | None = None,
        *,
        input_tokens: int = 100,
        output_tokens: int = 20,
    ) -> None:
        self.calls: list[JudgeRequest] = []
        self._respond = respond or (
            lambda _r: JudgeResponse(
                value=1.0, abstained=False, input_tokens=input_tokens, output_tokens=output_tokens
            )
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def score(self, request: JudgeRequest) -> JudgeResponse:
        self.calls.append(request)
        return self._respond(request)


def llm_config(
    cloud: str = "government",
    *,
    ident: str = "judge-a",
    row: str | None = None,
    approved: tuple[str, ...] = ("public", "internal", "cui"),
    max_output_tokens: int = 256,
) -> JudgeConfig:
    return JudgeConfig.model_validate(
        {
            "judge_config_id": ident,
            "version": "1",
            "judge_kind": "llm_judge",
            "cloud": cloud,
            "judge_model_id": f"{cloud}:c:foundry:modeldeployment:m",
            "judge_model_version": "1",
            "judge_prompt_version": "1",
            "capability_row_id": row or (GOV_ROW if cloud == "government" else COMM_ROW),
            "approved_classifications": approved,
            "max_output_tokens": max_output_tokens,
            "input_price_per_1k_tokens": "0.002",
            "output_price_per_1k_tokens": "0.008",
            "price_version": "p1",
        }
    )


def programmatic_config(cloud: str = "government") -> JudgeConfig:
    return JudgeConfig(
        judge_config_id="prog-a",
        version="1",
        judge_kind="programmatic",
        cloud=cloud,  # type: ignore[arg-type]
        program_version="p1",
        approved_classifications=("public", "internal", "cui", "restricted"),
        max_output_tokens=1,
    )


def commercial_matrix() -> CapabilityMatrix:
    """The shipped matrix plus an AVAILABLE commercial Foundry row (shipped one is unverified)."""
    row = CapabilityMatrixEntry.model_validate(
        {
            "schema_version": "1.1.0",
            "id": COMM_ROW,
            "service": "foundry",
            "feature": "base",
            "cloud": "commercial",
            "region": "global",
            "sku": None,
            "availability": "available",
            "ga_status": "unverified",
            "authorization_scope": "none_claimed",
            "source_url": "https://learn.microsoft.com/azure/foundry/reference/region-support",
            "observed_on": "2026-10-08",
            "notes": "test row",
        }
    )
    others = [r for r in load_matrix() if r.id != COMM_ROW]
    return matrix_from_rows([*others, row])


def rubric() -> RubricVersion:
    return RubricVersion(
        rubric_id=RUBRIC_ID,
        version=RUBRIC_VERSION,
        dimensions=("task_success", "tool_correctness", "groundedness"),
        criteria=(
            Criterion(criterion_id="c1", dimension="task_success", description="run succeeded"),
            Criterion(criterion_id="c2", dimension="tool_correctness", description="tool ok"),
        ),
        scale_min=0.0,
        scale_max=1.0,
    )


def make_registry(*configs: JudgeConfig) -> EvaluationRegistry:
    registry = EvaluationRegistry()
    registry.datasets.register(
        DatasetVersion.build(
            dataset_id=FRAME_ID,
            version=FRAME_VERSION,
            kind="sampling_frame",
            dimensions=("task_success", "tool_correctness"),
            items=(
                DatasetItem(
                    item_id="frame-1",
                    dimension="task_success",
                    classification="public",
                    payload={"frame": "archive spans"},
                ),
            ),
            data_state="redacted",
            created_at="2026-10-01T00:00:00Z",
        )
    )
    registry.rubrics.register(rubric())
    for config in configs:
        registry.judge_configs.register(config)
    return registry


def record(
    n: int,
    *,
    domain: str | None = "dom-a",
    agent: str | None = "agent-a",
    classification: str | None = "public",
    span_kind: str = "agent_run",
    outcome: str = "success",
    cloud: str = "government",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An archive-shaped record (NormalizedEvent dump): doc_id plus the telemetry contract."""
    contract: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": f"evt-{n:05d}",
        "event_time": f"2026-10-19T12:{n // 60 % 60:02d}:{n % 60:02d}Z",
        "cloud": cloud,
        "customer_id": CUSTOMER,
        "domain_id": domain,
        "source_id": "src1",
        "external_agent_id": agent,
        "canonical_agent_id": None if agent is None else f"{cloud}:{CUSTOMER}:src1:agent:{agent}",
        "span_kind": span_kind,
        "outcome": outcome,
        "duration_ms": 10 + n,
        "classification": classification,
        **(extra or {}),
    }
    return {"doc_id": f"{n:064x}", "contract": contract}


def population(
    *,
    domains: Iterable[str] = ("dom-a", "dom-b"),
    agents: Iterable[str] = ("agent-a", "agent-b"),
    classifications: Iterable[str | None] = ("public", "internal"),
    per_stratum: int = 10,
    cloud: str = "government",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = 0
    for dom in domains:
        for agent in agents:
            for cls in classifications:
                for _ in range(per_stratum):
                    out.append(
                        record(
                            n,
                            domain=dom,
                            agent=agent,
                            classification=cls,
                            cloud=cloud,
                            outcome="success" if n % 3 else "error",
                        )
                    )
                    n += 1
    return out


def ledger(
    *, run: BudgetLimits = HUGE, domain: BudgetLimits = HUGE, **overrides: BudgetLimits
) -> BudgetLedger:
    return BudgetLedger(run_limits=run, domain_limits=domain, domain_overrides=overrides or None)


def online_config(
    judge_config: JudgeConfig,
    *,
    cloud: str = "government",
    rate: float = 1.0,
    seed: int = 7,
    run_id: str = "run-1",
    tool_config: JudgeConfig | None = None,
) -> OnlineRunConfig:
    judges = {"task_success": judge_config, "tool_correctness": tool_config or judge_config}
    return OnlineRunConfig(
        run_id=run_id,
        cloud=cloud,  # type: ignore[arg-type]
        rubric=rubric(),
        judges=judges,  # type: ignore[arg-type]
        frame_dataset_id=FRAME_ID,
        frame_dataset_version=FRAME_VERSION,
        rate=rate,
        seed=seed,
    )


def make_service(
    judge: CountingJudge | Any,
    configs: Iterable[JudgeConfig],
    *,
    matrix: CapabilityMatrix | None = None,
    budget: BudgetLedger | None = None,
) -> EvaluationService:
    return EvaluationService(
        judge=judge,
        matrix=matrix or load_matrix(),
        registry=make_registry(*configs),
        ledger=budget or ledger(),
        clock=lambda: T0,
    )


def calibrated_report(config: JudgeConfig, dimension: str) -> CalibrationReport:
    """A calibrated ``CalibrationReport`` for a config and dimension (hand-built, no labels)."""
    return CalibrationReport(
        calibration_ref=f"cal-{config.judge_config_id}-{dimension}",
        dimension=dimension,  # type: ignore[arg-type]
        judge_config_id=config.judge_config_id,
        judge_config_version=config.version,
        label_set_version="ls1",
        calibrated_at=T0,
        state="calibrated",
        uncalibrated_reason=None,
        metric="accuracy",
        agreement=0.9,
        agreement_sample_size=30,
        agreement_interval=Interval.not_estimable(),
        bias=BiasEstimate(mean_difference=0.0, interval=Interval.not_estimable(), sample_size=30),
        bias_checks=(BiasCheckResult(check="length_bias", result="not_run"),),
        coverage=(),
        overall_coverage=StratumCoverage(
            stratum="all", judged=30, labelled=30, missing=0, label_fraction=1.0
        ),
        min_labels=20,
    )
