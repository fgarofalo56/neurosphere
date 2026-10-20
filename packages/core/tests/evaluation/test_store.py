"""Evaluation store: scope predicates, immutability, paging, calibration/coverage/drift records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import (
    BiasEstimate,
    CalibrationReport,
    DriftAlert,
    Interval,
    StratumCoverage,
)
from neurosphere_core.evaluation.store import (
    EvaluationConflictError,
    EvaluationStore,
    InMemoryEvaluationStore,
    SamplingCoverage,
    judge_config_key,
)
from neurosphere_core.scope import IdentityScope

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/schemas"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
T = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def make_scope(
    *, domains: tuple[str, ...] = (FINANCE,), customer: str = "contoso", cloud: str = "commercial"
) -> IdentityScope:
    doc = json.loads(
        (CONTRACTS / "scope/v1/examples/valid/identity-scope.viewer.json").read_text("utf-8")
    )
    doc["allowed_domains"] = list(domains)
    doc["roles"] = [{"role": "viewer", "domain_ids": list(domains)}]
    doc["customer_id"] = customer
    doc["cloud"] = cloud
    return IdentityScope._from_verified_contract(ContractScope.model_validate(doc))


def make_result(n: int, **overrides: Any) -> EvaluationResult:
    doc = json.loads(
        (
            CONTRACTS / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
        ).read_text("utf-8")
    )
    doc["evaluation_id"] = f"eval:r-{n:04d}"
    doc.update(overrides)
    return EvaluationResult.model_validate(doc)


def make_report(
    dimension: str = "groundedness", state: str = "calibrated", at: datetime = T
) -> CalibrationReport:
    cov = StratumCoverage(stratum="all", judged=10, labelled=6, missing=4, label_fraction=0.6)
    return CalibrationReport(
        calibration_ref="cal:1",
        dimension=dimension,  # type: ignore[arg-type]
        judge_config_id="judge",
        judge_config_version="1+2",
        label_set_version="labels-1",
        calibrated_at=at,
        state=state,  # type: ignore[arg-type]
        uncalibrated_reason=None,
        metric="accuracy",
        agreement=0.9,
        agreement_sample_size=6,
        agreement_interval=Interval.not_estimable(),
        bias=BiasEstimate(mean_difference=None, interval=Interval.not_estimable(), sample_size=0),
        bias_checks=(),
        coverage=(cov,),
        overall_coverage=cov,
        min_labels=1,
    )


async def test_protocol_and_idempotent_put() -> None:
    store = InMemoryEvaluationStore()
    assert isinstance(store, EvaluationStore)
    result = make_result(1)
    await store.put_result(result)
    await store.put_result(make_result(1))
    page = await store.list_results(make_scope(), FINANCE)
    assert [r.evaluation_id.root for r in page.items] == ["eval:r-0001"]


async def test_conflicting_put_is_rejected_and_original_kept() -> None:
    store = InMemoryEvaluationStore([make_result(1)])
    changed = make_result(1, status="partial")
    with pytest.raises(EvaluationConflictError) as err:
        await store.put_result(changed)
    assert err.value.http_status == 409
    (kept,) = (await store.list_results(make_scope(), FINANCE)).items
    assert kept.status == "completed"


async def test_old_results_stay_queryable_after_newer_ones() -> None:
    store = InMemoryEvaluationStore([make_result(1, completed_at="2026-09-01T00:00:00Z")])
    await store.put_result(make_result(2, completed_at="2026-10-01T00:00:00Z"))
    ids = [r.evaluation_id.root for r in await store.results(make_scope(), FINANCE)]
    assert ids == ["eval:r-0001", "eval:r-0002"]


async def test_other_domain_customer_and_cloud_are_absent() -> None:
    other_customer = make_result(
        2,
        customer_id="fabrikam",
        domain_id="commercial:fabrikam:catalog:domain:finance",
        subject_id="commercial:fabrikam:foundry:agent_version:a/v=1",
    )
    other_cloud = make_result(
        3,
        cloud="government",
        domain_id="government:contoso:catalog:domain:finance",
        subject_id="government:contoso:foundry:agent_version:a/v=1",
        data_handling={"data_state": "redacted", "boundary_cloud": "government"},
    )
    other_domain = make_result(4, domain_id=OPERATIONS)
    store = InMemoryEvaluationStore([make_result(1), other_customer, other_cloud, other_domain])
    scope = make_scope(domains=(FINANCE, OPERATIONS))
    got = [r.evaluation_id.root for r in (await store.list_results(scope, FINANCE)).items]
    assert got == ["eval:r-0001"]
    assert len(await store.results(scope, OPERATIONS)) == 1
    narrow = make_scope()
    assert (await store.list_results(narrow, OPERATIONS)).items == ()
    assert await store.results(narrow, OPERATIONS) == ()


async def test_filters_and_paging() -> None:
    results = [make_result(i) for i in range(1, 6)]
    store = InMemoryEvaluationStore(results)
    scope = make_scope()
    first = await store.list_results(scope, FINANCE, limit=2)
    assert [r.evaluation_id.root for r in first.items] == ["eval:r-0001", "eval:r-0002"]
    assert first.next_cursor is not None
    rest = await store.list_results(scope, FINANCE, cursor=first.next_cursor, limit=10)
    assert len(rest.items) == 3 and rest.next_cursor is None
    assert (await store.list_results(scope, FINANCE, dimension="safety")).items != ()
    assert (await store.list_results(scope, FINANCE, dimension="drift")).items == ()
    assert (await store.list_results(scope, FINANCE, subject_id="nope")).items == ()
    with pytest.raises(InvalidSchemaError):
        await store.list_results(scope, FINANCE, cursor="_w==")
    with pytest.raises(InvalidSchemaError):
        await store.list_results(scope, FINANCE, limit=0)


async def test_calibration_coverage_and_drift_are_scoped_and_newest_wins() -> None:
    store = InMemoryEvaluationStore()
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(state="uncalibrated"))
    later = datetime(2026, 10, 20, tzinfo=UTC)
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(at=later))
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(at=T))  # older
    await store.put_calibration("commercial", "fabrikam", FINANCE, make_report())
    reports = await store.calibrations(make_scope(), FINANCE)
    assert len(reports) == 1 and reports[0].state == "calibrated"
    assert await store.calibrations(make_scope(), OPERATIONS) == ()

    alert = DriftAlert(
        dimension="groundedness",
        subject_id="commercial:contoso:foundry:agent_version:a/v=1",
        detected_at="2026-10-19T00:00:00Z",
        statistic=0.4,
        threshold=0.25,
    )
    await store.put_drift_alert("commercial", "contoso", FINANCE, alert)
    await store.put_drift_alert("commercial", "contoso", OPERATIONS, alert)
    assert await store.drift_alerts(make_scope(), FINANCE) == (alert,)
    assert await store.drift_alerts(make_scope(), FINANCE, subject_id="x") == ()

    def cov(run: str, stratum: str, sampled: int, at: datetime) -> SamplingCoverage:
        return SamplingCoverage(
            cloud="commercial",
            customer_id="contoso",
            domain_id=FINANCE,
            run_id=run,
            stratum=stratum,
            sampled=sampled,
            population=None,
            coverage_fraction=None,
            recorded_at=at,
        )

    await store.put_coverage(cov("run1", "agent-a", 5, T))
    await store.put_coverage(cov("run2", "agent-a", 9, later))
    await store.put_coverage(cov("run2", "agent-b", 2, later))
    got = await store.coverage(make_scope(), FINANCE)
    assert [(c.stratum, c.sampled, c.population) for c in got] == [
        ("agent-a", 9, None),
        ("agent-b", 2, None),
    ]
    assert await store.coverage(make_scope(), OPERATIONS) == ()


def test_judge_config_key() -> None:
    llm = make_result(1).judge
    assert judge_config_key(llm) == (
        "commercial:contoso:foundry:model_deployment:judge-eastus",
        "2026-08-01+7",
    )
    prog = make_result(
        2, judge={"judge_kind": "programmatic", "program_version": "1"}, calibration=None
    ).judge
    assert judge_config_key(prog) is None
