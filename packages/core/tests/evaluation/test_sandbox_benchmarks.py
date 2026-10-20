"""Sandbox benchmark data: coverage, determinism, fixtures, labels, and contract validity."""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.evaluation.registry import (
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    check_result_references,
    judge_approval,
)

# ``sandbox`` lives at the repo root; make this module importable when run on its own.
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sandbox.evaluation import build  # noqa: E402
from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    PILOT_VERSION,
    load_fixture_judge,
    load_human_labels,
    load_registry,
    pilot_request,
)

DIMENSIONS = {"task_success", "groundedness", "safety", "tool_correctness"}


@pytest.fixture(scope="module")
def registry() -> EvaluationRegistry:
    return load_registry()


def _pilot(registry: EvaluationRegistry) -> DatasetVersion:
    pilot = registry.datasets.get(PILOT_DATASET_ID, PILOT_VERSION)
    assert pilot is not None
    return pilot


def _config(registry: EvaluationRegistry, ident: str) -> JudgeConfig:
    config = registry.judge_configs.latest(ident)
    assert config is not None
    return config


def test_committed_data_matches_the_deterministic_builder() -> None:
    for name, doc in build.build_all().items():
        committed = (build.DATA_DIR / name).read_text(encoding="utf-8")
        assert committed == build.render(doc), (
            f"{name} is stale; run python -m sandbox.evaluation.build"
        )


def test_everything_is_labelled_synthetic() -> None:
    for path in build.DATA_DIR.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["synthetic"] is True
        assert "SYNTHETIC" in doc["notice"]


def test_datasets_cover_the_four_dimensions(registry: EvaluationRegistry) -> None:
    covered: set[str] = set()
    for ident in registry.datasets.ids():
        for ds in registry.datasets.versions(ident):
            assert ds.data_state == "synthetic"
            covered.update(ds.dimensions)
    assert covered == DIMENSIONS


def test_pilot_set_has_fifty_items_with_mixed_classifications(
    registry: EvaluationRegistry,
) -> None:
    pilot = _pilot(registry)
    assert len(pilot.items) == 50
    counts = Counter(i.classification for i in pilot.items)
    assert counts["cui"] > 0 and counts["restricted"] > 0
    assert counts["public"] > 0 and counts["internal"] > 0


def test_judge_configs_have_the_designed_approvals(registry: EvaluationRegistry) -> None:
    commercial = _config(registry, "sbx-judge-commercial")
    government = _config(registry, "sbx-judge-government")
    programmatic = _config(registry, "sbx-judge-programmatic")
    assert (commercial.judge_kind, commercial.cloud) == ("llm_judge", "commercial")
    assert set(commercial.approved_classifications) == {"public", "internal"}
    assert (government.judge_kind, government.cloud) == ("llm_judge", "government")
    assert set(government.approved_classifications) == {"public", "internal", "cui"}
    assert programmatic.judge_kind == "programmatic"


async def test_fixtures_cover_exactly_the_approved_pairs(registry: EvaluationRegistry) -> None:
    pilot = _pilot(registry)
    judge = load_fixture_judge()
    for ident in ("sbx-judge-commercial", "sbx-judge-government"):
        config = _config(registry, ident)
        for item in pilot.items:
            approved, _ = judge_approval(config, item.classification, config.cloud)
            request = pilot_request(config, item)
            if approved:
                response = await judge.score(request)
                assert response.value is None or 0.0 <= response.value <= 1.0
            else:
                assert not judge.has_fixture(request)
    assert judge.call_count > 0


async def test_restricted_items_have_no_llm_fixture_and_cause_no_calls(
    registry: EvaluationRegistry,
) -> None:
    pilot = _pilot(registry)
    judge = load_fixture_judge()
    for ident in ("sbx-judge-commercial", "sbx-judge-government"):
        config = _config(registry, ident)
        for item in pilot.items:
            if judge_approval(config, item.classification, config.cloud)[0]:
                await judge.score(pilot_request(config, item))
    scored_ids = {c.item_id for c in judge.calls}
    restricted = {i.item_id for i in pilot.items if i.classification == "restricted"}
    assert restricted and not (scored_ids & restricted)


def test_human_labels_are_a_versioned_set_over_the_pilot(registry: EvaluationRegistry) -> None:
    labels = load_human_labels()
    assert labels.synthetic and labels.version
    assert (labels.dataset_id, labels.dataset_version) == (PILOT_DATASET_ID, PILOT_VERSION)
    assert {label.item_id for label in labels.labels} == {i.item_id for i in _pilot(registry).items}
    assert all(label.labeller.startswith("psn_") for label in labels.labels)


def _result_for(
    dataset: DatasetVersion, config: JudgeConfig, value: float, calibrated: bool
) -> dict[str, Any]:
    judge: dict[str, Any] = {"judge_kind": config.judge_kind}
    if config.judge_kind == "programmatic":
        judge["program_version"] = config.program_version
    else:
        judge.update(
            judge_model_id=config.judge_model_id,
            judge_model_version=config.judge_model_version,
            judge_prompt_version=config.judge_prompt_version,
        )
    n = len(dataset.items)
    return {
        "schema_version": "1.0.0",
        "evaluation_id": f"ev-{dataset.dataset_id}",
        "cloud": config.cloud,
        "customer_id": "sandbox",
        "domain_id": f"{config.cloud}:sandbox:catalog:domain:synthetic",
        "subject_id": f"{config.cloud}:sandbox:foundry:agentversion:synthetic-agent",
        "mode": "offline_benchmark",
        "status": "completed",
        "dataset": {"dataset_id": dataset.dataset_id, "dataset_version": dataset.version},
        "rubric": {"rubric_id": "sbx-rubric", "rubric_version": "1.0.0"},
        "judge": judge,
        "scores": [
            {
                "dimension": dataset.dimensions[0],
                "value": value,
                "scale": {"min": 0.0, "max": 1.0},
                "uncertainty": {
                    "method": "confidence_interval",
                    "lower": max(0.0, value - 0.1),
                    "upper": min(1.0, value + 0.1),
                    "level": 0.95,
                },
                "sample_size": n,
            }
        ],
        "sampling": {
            "method": "full",
            "sample_size": n,
            "population_size": n,
            "coverage_fraction": 1.0,
            "window": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
        },
        "calibration": (
            {
                "calibration_ref": "sbx-cal-1",
                "human_label_set_version": "1.0.0",
                "agreement": {"metric": "accuracy", "value": 0.85, "sample_size": n},
                "calibrated_at": "2026-10-01T00:00:00Z",
            }
            if calibrated
            else None
        ),
        "data_handling": {"data_state": dataset.data_state, "boundary_cloud": config.cloud},
        "started_at": "2026-10-01T00:00:00Z",
        "completed_at": "2026-10-01T01:00:00Z",
    }


def test_results_built_from_sandbox_datasets_validate_and_reference_registered_versions(
    registry: EvaluationRegistry,
) -> None:
    programmatic = _config(registry, "sbx-judge-programmatic")
    government = _config(registry, "sbx-judge-government")
    checked = 0
    for ident in registry.datasets.ids():
        for dataset in registry.datasets.versions(ident):
            result = EvaluationResult.model_validate(
                _result_for(dataset, programmatic, 0.5, calibrated=False)
            )
            check_result_references(result, registry)
            checked += 1
    assert checked == len(registry.datasets.ids())
    pilot = _pilot(registry)
    llm = EvaluationResult.model_validate(_result_for(pilot, government, 0.8, calibrated=True))
    check_result_references(llm, registry)
    assert llm.cloud == llm.data_handling.boundary_cloud == "government"


def test_production_code_does_not_import_sandbox() -> None:
    packages = Path(__file__).resolve().parents[3]
    offenders: list[str] = []
    for path in packages.rglob("*.py"):
        parts = set(path.parts)
        if "tests" in parts or ".venv" in parts or "node_modules" in parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] == "sandbox" for a in node.names
            ):
                offenders.append(str(path))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module or "").split(".")[0] == "sandbox"
            ):
                offenders.append(str(path))
    assert not offenders, offenders
