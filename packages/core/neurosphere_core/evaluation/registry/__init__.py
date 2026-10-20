"""Versioned datasets, rubrics and judge-config registry (PRP-16 item 1)."""

from neurosphere_core.evaluation.registry.models import (
    CLASSIFICATIONS,
    Classification,
    Cloud,
    Criterion,
    DatasetItem,
    DatasetVersion,
    Dimension,
    JudgeConfig,
    JudgeKind,
    RubricVersion,
    compute_content_hash,
    normalize_classification,
)
from neurosphere_core.evaluation.registry.policy import judge_approval, judge_availability
from neurosphere_core.evaluation.registry.references import (
    REASON_DATASET_UNREGISTERED,
    REASON_HUMAN_JUDGE,
    REASON_JUDGE_CLOUD_MISMATCH,
    REASON_JUDGE_UNREGISTERED,
    REASON_RUBRIC_UNREGISTERED,
    check_result_references,
)
from neurosphere_core.evaluation.registry.store import (
    EvaluationRegistry,
    EvaluationRegistryProtocol,
    VersionConflictError,
    VersionedRegistry,
)

__all__ = [
    "CLASSIFICATIONS",
    "REASON_DATASET_UNREGISTERED",
    "REASON_HUMAN_JUDGE",
    "REASON_JUDGE_CLOUD_MISMATCH",
    "REASON_JUDGE_UNREGISTERED",
    "REASON_RUBRIC_UNREGISTERED",
    "Classification",
    "Cloud",
    "Criterion",
    "DatasetItem",
    "DatasetVersion",
    "Dimension",
    "EvaluationRegistry",
    "EvaluationRegistryProtocol",
    "JudgeConfig",
    "JudgeKind",
    "RubricVersion",
    "VersionConflictError",
    "VersionedRegistry",
    "check_result_references",
    "compute_content_hash",
    "judge_approval",
    "judge_availability",
    "normalize_classification",
]
