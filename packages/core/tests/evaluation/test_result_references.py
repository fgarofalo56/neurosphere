"""check_result_references (delta D1) and the contract model's own required-version rules."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.registry import (
    REASON_DATASET_UNREGISTERED,
    REASON_HUMAN_JUDGE,
    REASON_JUDGE_CLOUD_MISMATCH,
    REASON_JUDGE_UNREGISTERED,
    REASON_RUBRIC_UNREGISTERED,
    DatasetItem,
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
    check_result_references,
)
from neurosphere_core.evaluation.registry.models import Criterion
from pydantic import ValidationError

SUBJECT = "commercial:acme:foundry:agentversion:agent-1"
MODEL = "commercial:acme:foundry:modeldeployment:judge-1"


def _registry() -> EvaluationRegistry:
    reg = EvaluationRegistry()
    reg.datasets.register(
        DatasetVersion.build(
            dataset_id="ds-1",
            version="1.0.0",
            kind="offline_benchmark",
            dimensions=("groundedness",),
            items=(
                DatasetItem(
                    item_id="i-1", dimension="groundedness", classification="public", payload={}
                ),
            ),
            data_state="synthetic",
            created_at="2026-10-01T00:00:00Z",
        )
    )
    reg.rubrics.register(
        RubricVersion(
            rubric_id="rb-1",
            version="1.0.0",
            dimensions=("groundedness",),
            criteria=(Criterion(criterion_id="c-1", dimension="groundedness", description="d"),),
            scale_min=0.0,
            scale_max=1.0,
        )
    )
    reg.judge_configs.register(
        JudgeConfig(
            judge_config_id="jc-llm",
            version="1.0.0",
            judge_kind="llm_judge",
            cloud="commercial",
            judge_model_id=MODEL,
            judge_model_version="2026-04-14",
            judge_prompt_version="p1",
            capability_row_id="foundry.base.commercial.global.any",
            approved_classifications=("public",),
            max_output_tokens=100,
            input_price_per_1k_tokens="0.001",
            output_price_per_1k_tokens="0.002",
            price_version="pv1",
        )
    )
    reg.judge_configs.register(
        JudgeConfig(
            judge_config_id="jc-prog",
            version="1.0.0",
            judge_kind="programmatic",
            cloud="commercial",
            program_version="prog-1",
            approved_classifications=("public",),
            max_output_tokens=1,
        )
    )
    return reg


def _doc() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "evaluation_id": "ev-1",
        "cloud": "commercial",
        "customer_id": "acme",
        "domain_id": "commercial:acme:catalog:domain:finance",
        "subject_id": SUBJECT,
        "mode": "offline_benchmark",
        "status": "completed",
        "dataset": {"dataset_id": "ds-1", "dataset_version": "1.0.0"},
        "rubric": {"rubric_id": "rb-1", "rubric_version": "1.0.0"},
        "judge": {
            "judge_kind": "llm_judge",
            "judge_model_id": MODEL,
            "judge_model_version": "2026-04-14",
            "judge_prompt_version": "p1",
        },
        "scores": [
            {
                "dimension": "groundedness",
                "value": 0.8,
                "scale": {"min": 0.0, "max": 1.0},
                "uncertainty": {
                    "method": "confidence_interval",
                    "lower": 0.6,
                    "upper": 0.9,
                    "level": 0.95,
                },
                "sample_size": 10,
            }
        ],
        "sampling": {
            "method": "full",
            "sample_size": 10,
            "population_size": 10,
            "coverage_fraction": 1.0,
            "window": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
        },
        "calibration": {
            "calibration_ref": "cal-1",
            "human_label_set_version": "1.0.0",
            "agreement": {"metric": "accuracy", "value": 0.9, "sample_size": 10},
            "calibrated_at": "2026-10-01T00:00:00Z",
        },
        "data_handling": {"data_state": "synthetic", "boundary_cloud": "commercial"},
        "started_at": "2026-10-01T00:00:00Z",
        "completed_at": "2026-10-01T01:00:00Z",
    }


def _result(**edits: Any) -> EvaluationResult:
    doc = _doc()
    for path, value in edits.items():
        node = doc
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return EvaluationResult.model_validate(doc)


def _reason(result: EvaluationResult) -> str | None:
    with pytest.raises(InvalidSchemaError) as exc:
        check_result_references(result, _registry())
    return exc.value.reason


def test_registered_llm_and_programmatic_results_pass() -> None:
    check_result_references(_result(), _registry())
    prog = _result(
        judge={"judge_kind": "programmatic", "program_version": "prog-1"}, calibration=None
    )
    check_result_references(prog, _registry())


def test_unregistered_dataset_version() -> None:
    assert _reason(_result(dataset={"dataset_id": "ds-1", "dataset_version": "9"})) == (
        REASON_DATASET_UNREGISTERED
    )
    assert _reason(_result(dataset={"dataset_id": "other", "dataset_version": "1.0.0"})) == (
        REASON_DATASET_UNREGISTERED
    )


def test_unregistered_rubric_version() -> None:
    assert _reason(_result(rubric={"rubric_id": "rb-1", "rubric_version": "9"})) == (
        REASON_RUBRIC_UNREGISTERED
    )


def test_human_judge_is_rejected() -> None:
    assert _reason(_result(judge={"judge_kind": "human"}, calibration=None)) == (REASON_HUMAN_JUDGE)


@pytest.mark.parametrize("field", ["judge_model_version", "judge_prompt_version"])
def test_unregistered_llm_judge_versions(field: str) -> None:
    judge = {**_doc()["judge"], field: "unregistered"}
    assert _reason(_result(judge=judge)) == REASON_JUDGE_UNREGISTERED


def test_unregistered_llm_judge_model_id() -> None:
    judge = {**_doc()["judge"], "judge_model_id": "commercial:acme:foundry:modeldeployment:z"}
    assert _reason(_result(judge=judge)) == REASON_JUDGE_UNREGISTERED


def test_unregistered_program_version() -> None:
    judge = {"judge_kind": "programmatic", "program_version": "prog-2"}
    assert _reason(_result(judge=judge, calibration=None)) == REASON_JUDGE_UNREGISTERED


def test_judge_config_from_other_cloud_is_rejected() -> None:
    gov_model = "government:acme:foundry:modeldeployment:judge-1"
    reg = EvaluationRegistry()
    reg.judge_configs.register(
        JudgeConfig(
            judge_config_id="jc-gov",
            version="1",
            judge_kind="llm_judge",
            cloud="government",
            judge_model_id=gov_model,
            judge_model_version="2026-04-14",
            judge_prompt_version="p1",
            capability_row_id="row",
            approved_classifications=("public",),
            max_output_tokens=10,
            input_price_per_1k_tokens="0.001",
            output_price_per_1k_tokens="0.001",
            price_version="pv1",
        )
    )
    base = _registry()
    reg.datasets.register(base.datasets.get("ds-1", "1.0.0"))  # type: ignore[arg-type]
    reg.rubrics.register(base.rubrics.get("rb-1", "1.0.0"))  # type: ignore[arg-type]
    result = _result(
        judge={
            "judge_kind": "llm_judge",
            "judge_model_id": gov_model,
            "judge_model_version": "2026-04-14",
            "judge_prompt_version": "p1",
        }
    )
    with pytest.raises(InvalidSchemaError) as exc:
        check_result_references(result, reg)
    assert exc.value.reason == REASON_JUDGE_CLOUD_MISMATCH


# --- the generated contract model itself rejects missing versions (AC item 1) ---


def _without(path: str) -> dict[str, Any]:
    doc = copy.deepcopy(_doc())
    node = doc
    *parents, leaf = path.split("__")
    for p in parents:
        node = node[p]
    del node[leaf]
    return doc


_SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "schemas"
    / "evaluation"
    / "v1"
    / "evaluation-result.schema.json"
)
_LLM_JUDGE_PATHS = [
    "judge__judge_model_id",
    "judge__judge_model_version",
    "judge__judge_prompt_version",
]


@pytest.mark.parametrize("path", ["dataset__dataset_version", "rubric__rubric_version"])
def test_contract_model_rejects_missing_dataset_or_rubric_version(path: str) -> None:
    with pytest.raises(ValidationError):
        EvaluationResult.model_validate(_without(path))


@pytest.mark.parametrize(
    "path", ["dataset__dataset_version", "rubric__rubric_version", *_LLM_JUDGE_PATHS]
)
def test_contract_schema_rejects_missing_version(path: str) -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(_doc()))  # the baseline document is valid
    assert list(validator.iter_errors(_without(path)))


@pytest.mark.parametrize("path", _LLM_JUDGE_PATHS)
def test_llm_judge_versions_missing_in_model_are_caught_by_registry_check(path: str) -> None:
    # The generated model leaves judge version fields optional (the schema's if/then is not
    # expressed in Pydantic), so the registry check is the second line of defence.
    result = EvaluationResult.model_validate(_without(path))
    assert _reason(result) == REASON_JUDGE_UNREGISTERED


def test_contract_rejects_missing_dataset_and_rubric_blocks() -> None:
    for key in ("dataset", "rubric", "judge"):
        doc = _doc()
        del doc[key]
        with pytest.raises(ValidationError):
            EvaluationResult.model_validate(doc)
