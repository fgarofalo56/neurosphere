"""Load the committed SYNTHETIC evaluation benchmark data (PRP-16 item 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from neurosphere_core.evaluation.judge import RecordedFixtureJudge
from neurosphere_core.evaluation.registry import (
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
)
from pydantic import BaseModel, ConfigDict, Field

from sandbox.evaluation.build import DATA_DIR, PILOT_DATASET_ID, PILOT_VERSION, pilot_request

__all__ = [
    "PILOT_DATASET_ID",
    "PILOT_VERSION",
    "HumanLabel",
    "HumanLabelSet",
    "load_fixture_judge",
    "load_human_labels",
    "load_registry",
    "pilot_request",
]


class HumanLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    value: Annotated[float, Field(ge=0.0, le=1.0)]
    labeller: str


class HumanLabelSet(BaseModel):
    """A versioned synthetic human-label set (later input to calibration)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    synthetic: bool
    notice: str
    label_set_id: str
    version: str
    dataset_id: str
    dataset_version: str
    labels: tuple[HumanLabel, ...]


def _read(name: str, data_dir: Path) -> Any:
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def load_registry(data_dir: Path = DATA_DIR) -> EvaluationRegistry:
    """A registry holding every sandbox dataset, rubric and judge config."""
    registry = EvaluationRegistry()
    for raw in _read("datasets.json", data_dir)["datasets"]:
        registry.datasets.register(DatasetVersion.model_validate(raw))
    for raw in _read("rubrics.json", data_dir)["rubrics"]:
        registry.rubrics.register(RubricVersion.model_validate(raw))
    for raw in _read("judge_configs.json", data_dir)["judge_configs"]:
        registry.judge_configs.register(JudgeConfig.model_validate(raw))
    return registry


def load_fixture_judge(data_dir: Path = DATA_DIR) -> RecordedFixtureJudge:
    return RecordedFixtureJudge.from_file(data_dir / "judge_fixtures.json")


def load_human_labels(data_dir: Path = DATA_DIR) -> HumanLabelSet:
    return HumanLabelSet.model_validate(_read("human_labels.json", data_dir))
