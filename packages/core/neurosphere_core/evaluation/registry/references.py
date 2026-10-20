"""Check that an ``EvaluationResult`` references only registered versions (PRP-16 delta D1).

The contract schema requires dataset, rubric and judge versions; this adds the part JSON Schema
cannot express: the referenced versions must exist in the registry. Human-judged results are not
part of this pipeline (human labels are calibration input).
"""

from __future__ import annotations

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.registry.models import JudgeConfig
from neurosphere_core.evaluation.registry.store import EvaluationRegistryProtocol

__all__ = [
    "REASON_DATASET_UNREGISTERED",
    "REASON_HUMAN_JUDGE",
    "REASON_JUDGE_CLOUD_MISMATCH",
    "REASON_JUDGE_UNREGISTERED",
    "REASON_RUBRIC_UNREGISTERED",
    "check_result_references",
]

REASON_DATASET_UNREGISTERED = "dataset_version_unregistered"
REASON_RUBRIC_UNREGISTERED = "rubric_version_unregistered"
REASON_HUMAN_JUDGE = "human_judge_not_allowed"
REASON_JUDGE_UNREGISTERED = "judge_config_unregistered"
REASON_JUDGE_CLOUD_MISMATCH = "judge_cloud_mismatch"


def _matches(config: JudgeConfig, result: EvaluationResult) -> bool:
    judge = result.judge
    if judge.judge_kind != config.judge_kind:
        return False
    if judge.judge_kind == "programmatic":
        return judge.program_version is not None and judge.program_version.root == (
            config.program_version
        )
    return (
        judge.judge_model_id is not None
        and judge.judge_model_version is not None
        and judge.judge_prompt_version is not None
        and judge.judge_model_id.root == config.judge_model_id
        and judge.judge_model_version.root == config.judge_model_version
        and judge.judge_prompt_version.root == config.judge_prompt_version
    )


def check_result_references(result: EvaluationResult, registry: EvaluationRegistryProtocol) -> None:
    """Raise ``InvalidSchemaError`` (distinct ``reason``) if a reference is not registered."""
    if result.judge.judge_kind == "human":
        raise InvalidSchemaError(
            "human-judged results are not accepted; human labels feed calibration",
            reason=REASON_HUMAN_JUDGE,
        )
    dataset = result.dataset
    if registry.datasets.get(dataset.dataset_id.root, dataset.dataset_version.root) is None:
        raise InvalidSchemaError(
            "dataset version is not registered", reason=REASON_DATASET_UNREGISTERED
        )
    rubric = result.rubric
    if registry.rubrics.get(rubric.rubric_id.root, rubric.rubric_version.root) is None:
        raise InvalidSchemaError(
            "rubric version is not registered", reason=REASON_RUBRIC_UNREGISTERED
        )
    candidates = [
        config
        for ident in registry.judge_configs.ids()
        for config in registry.judge_configs.versions(ident)
        if _matches(config, result)
    ]
    if not candidates:
        raise InvalidSchemaError(
            "judge versions match no registered judge config", reason=REASON_JUDGE_UNREGISTERED
        )
    if all(config.cloud != result.cloud for config in candidates):
        raise InvalidSchemaError(
            "matching judge config belongs to a different cloud", reason=REASON_JUDGE_CLOUD_MISMATCH
        )
