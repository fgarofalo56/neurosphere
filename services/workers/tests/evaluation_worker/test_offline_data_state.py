"""Offline runs trust the registry's data_state, never the caller's label (the hash omits it)."""

from __future__ import annotations

import pytest
from neurosphere_core.capabilities import load_matrix
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.registry import DatasetItem, DatasetVersion, EvaluationRegistry
from neurosphere_workers.evaluation.service import EvaluationService, OfflineRunConfig

from .support import T0, CountingJudge, ledger, llm_config, make_registry, rubric

DOMAIN = "government:cust1:neurosphere:domain:dom-a"
SUBJECT = "government:cust1:foundry:agent:agent-a"


def _dataset(data_state: str, payload: dict[str, str]) -> DatasetVersion:
    return DatasetVersion.build(
        dataset_id=f"bench-{data_state}",
        version="1",
        kind="offline_benchmark",
        dimensions=("task_success",),
        items=(
            DatasetItem(
                item_id="item-1",
                dimension="task_success",
                classification="public",
                payload=payload,
            ),
        ),
        data_state=data_state,  # type: ignore[arg-type]
        created_at="2026-10-01T00:00:00Z",
    )


def _run(dataset: DatasetVersion) -> tuple[EvaluationService, OfflineRunConfig, CountingJudge]:
    judge_config = llm_config()
    registry: EvaluationRegistry = make_registry(judge_config)
    registry.datasets.register(dataset)
    judge = CountingJudge()
    service = EvaluationService(
        judge=judge,
        matrix=load_matrix(),
        registry=registry,
        ledger=ledger(),
        clock=lambda: T0,
    )
    config = OfflineRunConfig(
        run_id="off-ds",
        cloud="government",
        rubric=rubric(),
        judges={"task_success": judge_config},
        customer_id="cust1",
        domain_id=DOMAIN,
        subject_id=SUBJECT,
    )
    return service, config, judge


@pytest.mark.parametrize("registered", ["redacted", "approved"])
async def test_relabelled_dataset_is_rejected_before_any_judge_call(registered: str) -> None:
    stored = _dataset(registered, {"response": "full model answer"})
    service, config, judge = _run(stored)
    relabelled = stored.model_copy(update={"data_state": "synthetic"})
    assert relabelled.content_hash == stored.content_hash  # the hash does not cover data_state
    with pytest.raises(InvalidSchemaError) as exc:
        await service.run_offline(relabelled, config)
    assert getattr(exc.value, "reason", None) == "dataset_data_state_mismatch"
    assert judge.call_count == 0


@pytest.mark.parametrize("field", ["response", "prompt"])
async def test_registered_non_synthetic_body_payload_is_skipped(field: str) -> None:
    stored = _dataset("redacted", {field: "raw body text"})
    service, config, judge = _run(stored)
    report = await service.run_offline(stored, config)
    assert judge.call_count == 0
    assert report.skip_counts == {"body_fields_present": 1}
    assert report.data_state == "redacted"


async def test_registered_synthetic_dataset_still_runs_with_body_field() -> None:
    stored = _dataset("synthetic", {"response": "synthetic safety item"})
    service, config, judge = _run(stored)
    report = await service.run_offline(stored, config)
    assert judge.call_count == 1
    assert report.data_state == "synthetic"
    assert report.skip_counts == {}
