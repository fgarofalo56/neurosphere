"""Registry versioning: append-only, idempotent, conflicts rejected, old versions retrievable."""

from __future__ import annotations

import pytest
from neurosphere_core.evaluation.registry import (
    DatasetItem,
    DatasetVersion,
    EvaluationRegistry,
    JudgeConfig,
    RubricVersion,
    VersionConflictError,
    compute_content_hash,
    normalize_classification,
)
from neurosphere_core.evaluation.registry.models import Criterion
from pydantic import ValidationError


def _item(n: int, text: str = "a") -> DatasetItem:
    return DatasetItem(
        item_id=f"it-{n}", dimension="groundedness", classification="public", payload={"t": text}
    )


def _dataset(version: str = "1.0.0", text: str = "a", created_at: str = "2026-10-01T00:00:00Z"):
    return DatasetVersion.build(
        dataset_id="ds-1",
        version=version,
        kind="offline_benchmark",
        dimensions=("groundedness",),
        items=(_item(1, text), _item(2, text)),
        data_state="synthetic",
        created_at=created_at,
    )


def _rubric(version: str = "1.0.0", scale_max: float = 1.0) -> RubricVersion:
    return RubricVersion(
        rubric_id="rb-1",
        version=version,
        dimensions=("groundedness",),
        criteria=(Criterion(criterion_id="c-1", dimension="groundedness", description="d"),),
        scale_min=0.0,
        scale_max=scale_max,
    )


def _judge(version: str = "1.0.0", **over: object) -> JudgeConfig:
    base: dict[str, object] = {
        "judge_config_id": "jc-1",
        "version": version,
        "judge_kind": "programmatic",
        "cloud": "commercial",
        "program_version": "p1",
        "approved_classifications": ("public",),
        "max_output_tokens": 10,
    }
    return JudgeConfig.model_validate({**base, **over})


def test_identical_reregistration_is_a_noop() -> None:
    reg = EvaluationRegistry()
    first = reg.datasets.register(_dataset())
    again = reg.datasets.register(_dataset(created_at="2026-10-02T00:00:00Z"))
    assert again is first
    assert len(reg.datasets.versions("ds-1")) == 1


def test_conflicting_content_for_same_version_is_rejected_and_not_applied() -> None:
    reg = EvaluationRegistry()
    original = reg.datasets.register(_dataset(text="a"))
    with pytest.raises(VersionConflictError) as exc:
        reg.datasets.register(_dataset(text="b"))
    assert exc.value.reason == "version_content_conflict"
    assert reg.datasets.get("ds-1", "1.0.0") is original


def test_rubric_and_judge_conflicts_are_rejected() -> None:
    reg = EvaluationRegistry()
    reg.rubrics.register(_rubric())
    with pytest.raises(VersionConflictError):
        reg.rubrics.register(_rubric(scale_max=5.0))
    reg.judge_configs.register(_judge())
    with pytest.raises(VersionConflictError):
        reg.judge_configs.register(_judge(max_output_tokens=11))


def test_revise_dataset_creates_new_version_and_keeps_old() -> None:
    reg = EvaluationRegistry()
    v1 = reg.datasets.register(_dataset())
    v2 = reg.revise_dataset("ds-1", "1.1.0", items=(_item(1, "z"), _item(2, "z")))
    assert v2.version == "1.1.0"
    assert v2.content_hash != v1.content_hash
    assert reg.datasets.get("ds-1", "1.0.0") is v1
    assert reg.datasets.get("ds-1", "1.1.0") is v2
    assert [d.version for d in reg.datasets.versions("ds-1")] == ["1.0.0", "1.1.0"]
    assert reg.datasets.latest("ds-1") is v2
    assert v1.items[0].payload == {"t": "a"}  # old version untouched


def test_revise_rubric_and_judge_config() -> None:
    reg = EvaluationRegistry()
    reg.rubrics.register(_rubric())
    reg.judge_configs.register(_judge())
    r2 = reg.revise_rubric("rb-1", "2.0.0", scale_max=5.0)
    j2 = reg.revise_judge_config("jc-1", "1.1.0", max_output_tokens=99)
    assert r2.scale_max == 5.0 and reg.rubrics.get("rb-1", "1.0.0") is not None
    assert reg.rubrics.get("rb-1", "1.0.0").scale_max == 1.0  # type: ignore[union-attr]
    assert j2.max_output_tokens == 99
    assert reg.judge_configs.get("jc-1", "1.0.0").max_output_tokens == 10  # type: ignore[union-attr]


def test_revise_unknown_id_and_same_version_different_content() -> None:
    reg = EvaluationRegistry()
    with pytest.raises(KeyError):
        reg.revise_rubric("nope", "2.0.0")
    reg.rubrics.register(_rubric())
    with pytest.raises(VersionConflictError):
        reg.revise_rubric("rb-1", "1.0.0", scale_max=9.0)


def test_unknown_lookups_are_none_or_empty() -> None:
    reg = EvaluationRegistry()
    assert reg.datasets.get("x", "1") is None
    assert reg.datasets.versions("x") == ()
    assert reg.datasets.latest("x") is None


def test_models_are_frozen() -> None:
    ds = _dataset()
    with pytest.raises(ValidationError):
        ds.version = "9"  # type: ignore[misc]


def test_content_hash_must_match_content() -> None:
    good = _dataset()
    tampered = good.model_dump()
    tampered["items"] = (_item(1, "different"), _item(2, "a"))
    with pytest.raises(ValidationError, match="content_hash"):
        DatasetVersion.model_validate(tampered)
    assert good.content_hash == compute_content_hash(good.kind, good.dimensions, good.items)


def test_dataset_rejects_duplicate_items_and_undeclared_dimension() -> None:
    with pytest.raises(ValidationError, match="duplicate item_id"):
        DatasetVersion.build(
            dataset_id="ds-2",
            version="1",
            kind="sampling_frame",
            dimensions=("groundedness",),
            items=(_item(1), _item(1)),
            data_state="redacted",
            created_at="2026-10-01T00:00:00Z",
        )
    with pytest.raises(ValidationError, match="not declared"):
        DatasetVersion.build(
            dataset_id="ds-2",
            version="1",
            kind="offline_benchmark",
            dimensions=("safety",),
            items=(_item(1),),
            data_state="approved",
            created_at="2026-10-01T00:00:00Z",
        )


def test_judge_config_kind_rules() -> None:
    with pytest.raises(ValidationError):
        _judge(judge_kind="human")
    with pytest.raises(ValidationError, match="program_version"):
        _judge(program_version=None)
    with pytest.raises(ValidationError, match="requires"):
        _judge(judge_kind="llm_judge", program_version=None)
    llm: dict[str, object] = {
        "judge_kind": "llm_judge",
        "program_version": None,
        "judge_model_id": "government:c:s:t:m",
        "judge_model_version": "1",
        "judge_prompt_version": "1",
        "capability_row_id": "row",
        "input_price_per_1k_tokens": "0.001",
        "output_price_per_1k_tokens": "0.002",
        "price_version": "p1",
    }
    with pytest.raises(ValidationError, match="cloud segment"):
        _judge(**llm)  # commercial config with a government model id
    assert _judge(cloud="government", **llm).judge_kind == "llm_judge"
    with pytest.raises(ValidationError):
        _judge(**{**llm, "cloud": "government", "input_price_per_1k_tokens": 0.001})


def test_normalize_classification_fails_closed() -> None:
    assert normalize_classification("cui") == "cui"
    assert normalize_classification(None) == "restricted"
    assert normalize_classification("CUI") == "restricted"
    assert normalize_classification("confidential") == "restricted"
