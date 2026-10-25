"""EvaluationStore protocol conformance checks, shared by every backend.

Each check takes a FRESH, empty store. ``CHECKS`` maps a check name to the coroutine function; the
in-memory + fake-container suite and the emulator suite (``tests/integration/stores_cosmos``)
both parametrize over it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
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
    SamplingCoverage,
)
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/schemas"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
FABRIKAM_FINANCE = "commercial:fabrikam:catalog:domain:finance"
AGENT = "commercial:contoso:foundry:agent_version:support-bot/v=3"
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
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(doc)
    )


def make_result(n: int | str, **overrides: Any) -> EvaluationResult:
    doc = json.loads(
        (
            CONTRACTS / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
        ).read_text("utf-8")
    )
    doc["evaluation_id"] = f"eval:r-{n:04d}" if isinstance(n, int) else n
    doc.update(overrides)
    return EvaluationResult.model_validate(doc)


def make_report(
    dimension: str = "groundedness",
    state: str = "calibrated",
    at: datetime = T,
    judge_config_id: str | None = "judge",
) -> CalibrationReport:
    cov = StratumCoverage(stratum="all", judged=10, labelled=6, missing=4, label_fraction=0.6)
    return CalibrationReport(
        calibration_ref="cal:1",
        dimension=dimension,  # type: ignore[arg-type]
        judge_config_id=judge_config_id,
        judge_config_version="1+2" if judge_config_id else None,
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


def make_alert(at: str = "2026-10-19T00:00:00Z", dimension: str = "groundedness") -> DriftAlert:
    return DriftAlert(
        dimension=dimension,  # type: ignore[arg-type]
        subject_id=AGENT,
        detected_at=at,
        statistic=0.4,
        threshold=0.25,
    )


def make_cov(
    run: str,
    stratum: str,
    sampled: int,
    at: datetime,
    *,
    customer: str = "contoso",
    domain: str = FINANCE,
    population: int | None = None,
) -> SamplingCoverage:
    return SamplingCoverage(
        cloud="commercial",
        customer_id=customer,
        domain_id=domain,
        run_id=run,
        stratum=stratum,
        sampled=sampled,
        population=population,
        coverage_fraction=None,
        recorded_at=at,
    )


def other_customer_result(n: int) -> EvaluationResult:
    return make_result(
        n,
        customer_id="fabrikam",
        domain_id=FABRIKAM_FINANCE,
        subject_id="commercial:fabrikam:foundry:agent_version:a/v=1",
    )


def eval_ids(items: Any) -> list[str]:
    return [r.evaluation_id.root for r in items]


Check = Callable[[EvaluationStore], Awaitable[None]]


async def check_satisfies_protocol(store: EvaluationStore) -> None:
    assert isinstance(store, EvaluationStore)


async def check_put_result_is_idempotent_and_conflict_is_rejected(store: EvaluationStore) -> None:
    await store.put_result(make_result(1))
    await store.put_result(make_result(1))
    page = await store.list_results(make_scope(), FINANCE)
    assert eval_ids(page.items) == ["eval:r-0001"]
    with pytest.raises(EvaluationConflictError) as err:
        await store.put_result(make_result(1, status="partial"))
    assert err.value.http_status == 409
    (kept,) = (await store.list_results(make_scope(), FINANCE)).items
    assert kept.status == "completed"


async def check_old_results_stay_queryable(store: EvaluationStore) -> None:
    await store.put_result(make_result(1, completed_at="2026-09-01T00:00:00Z"))
    await store.put_result(make_result(2, completed_at="2026-10-01T00:00:00Z"))
    assert eval_ids(await store.results(make_scope(), FINANCE)) == ["eval:r-0001", "eval:r-0002"]


async def check_list_results_orders_and_pages(store: EvaluationStore) -> None:
    for n in (4, 1, 5, 3, 2):
        await store.put_result(make_result(n))
    scope = make_scope()
    first = await store.list_results(scope, FINANCE, limit=2)
    assert eval_ids(first.items) == ["eval:r-0001", "eval:r-0002"]
    assert first.next_cursor is not None
    second = await store.list_results(scope, FINANCE, cursor=first.next_cursor, limit=2)
    assert eval_ids(second.items) == ["eval:r-0003", "eval:r-0004"]
    assert second.next_cursor is not None
    last = await store.list_results(scope, FINANCE, cursor=second.next_cursor, limit=2)
    assert eval_ids(last.items) == ["eval:r-0005"]
    assert last.next_cursor is None
    exact = await store.list_results(scope, FINANCE, limit=5)
    assert len(exact.items) == 5
    assert exact.next_cursor is None


async def check_result_filters(store: EvaluationStore) -> None:
    other_subject = "commercial:contoso:foundry:agent_version:other-bot/v=1"
    await store.put_result(make_result(1))
    await store.put_result(make_result(2, subject_id=other_subject))
    scope = make_scope()
    assert eval_ids((await store.list_results(scope, FINANCE, subject_id=other_subject)).items) == [
        "eval:r-0002"
    ]
    assert eval_ids((await store.list_results(scope, FINANCE, subject_id=AGENT)).items) == [
        "eval:r-0001"
    ]
    assert len((await store.list_results(scope, FINANCE, dimension="safety")).items) == 2
    assert (await store.list_results(scope, FINANCE, dimension="drift")).items == ()
    assert (await store.list_results(scope, FINANCE, subject_id="nope")).items == ()
    assert eval_ids(await store.results(scope, FINANCE, subject_id=other_subject)) == [
        "eval:r-0002"
    ]


async def check_invalid_input(store: EvaluationStore) -> None:
    scope = make_scope()
    with pytest.raises(InvalidSchemaError):
        await store.list_results(scope, FINANCE, cursor="_w==")
    with pytest.raises(InvalidSchemaError):
        await store.list_results(scope, FINANCE, limit=0)
    with pytest.raises(InvalidSchemaError):
        await store.list_results(scope, FINANCE, limit=MAX_PAGE_SIZE + 1)
    await store.list_results(scope, FINANCE, limit=MAX_PAGE_SIZE)


async def check_ids_with_forbidden_key_characters_round_trip(store: EvaluationStore) -> None:
    slashed = make_result("eval:run/with/slashes=1")
    await store.put_result(slashed)
    await store.put_result(slashed)
    assert (await store.list_results(make_scope(), FINANCE)).items == (slashed,)
    with pytest.raises(EvaluationConflictError):
        await store.put_result(make_result("eval:run/with/slashes=1", status="failed"))


async def check_result_domain_customer_and_cloud_isolation(store: EvaluationStore) -> None:
    other_cloud = make_result(
        3,
        cloud="government",
        domain_id="government:contoso:catalog:domain:finance",
        subject_id="government:contoso:foundry:agent_version:a/v=1",
        data_handling={"data_state": "redacted", "boundary_cloud": "government"},
    )
    cloud_clash = make_result(
        5,
        cloud="government",
        data_handling={"data_state": "redacted", "boundary_cloud": "government"},
    )  # same customer and domain id as the scope's, wrong cloud
    for item in (
        make_result(1),
        other_customer_result(2),
        other_cloud,
        make_result(4, domain_id=OPERATIONS),
        cloud_clash,
    ):
        await store.put_result(item)
    scope = make_scope(domains=(FINANCE, OPERATIONS))
    assert eval_ids((await store.list_results(scope, FINANCE)).items) == ["eval:r-0001"]
    assert eval_ids(await store.results(scope, FINANCE)) == ["eval:r-0001"]
    assert eval_ids(await store.results(scope, OPERATIONS)) == ["eval:r-0004"]
    narrow = make_scope()
    assert (await store.list_results(narrow, OPERATIONS)).items == ()
    assert await store.results(narrow, OPERATIONS) == ()
    fabrikam = make_scope(domains=(FABRIKAM_FINANCE,), customer="fabrikam")
    assert eval_ids(await store.results(fabrikam, FABRIKAM_FINANCE)) == ["eval:r-0002"]
    # Addressing another customer's domain with this customer's scope finds nothing.
    assert await store.results(scope, FABRIKAM_FINANCE) == ()


async def check_calibration_newest_wins_and_is_scoped(store: EvaluationStore) -> None:
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(state="uncalibrated"))
    later = T + timedelta(days=1)
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(at=later))
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(at=T))  # older
    await store.put_calibration("commercial", "fabrikam", FABRIKAM_FINANCE, make_report())
    await store.put_calibration("commercial", "contoso", OPERATIONS, make_report())
    reports = await store.calibrations(make_scope(), FINANCE)
    assert len(reports) == 1
    assert reports[0].state == "calibrated"
    assert reports[0].calibrated_at == later
    assert await store.calibrations(make_scope(domains=(FINANCE,)), OPERATIONS) == ()
    assert await store.calibrations(make_scope(), FABRIKAM_FINANCE) == ()
    other_cloud = make_scope(
        cloud="government", domains=("government:contoso:catalog:domain:finance",)
    )
    assert await store.calibrations(other_cloud, "government:contoso:catalog:domain:finance") == ()


async def check_calibration_keys_and_order(store: EvaluationStore) -> None:
    await store.put_calibration("commercial", "contoso", FINANCE, make_report("safety"))
    await store.put_calibration("commercial", "contoso", FINANCE, make_report("groundedness"))
    await store.put_calibration(
        "commercial", "contoso", FINANCE, make_report("groundedness", judge_config_id=None)
    )
    await store.put_calibration(
        "commercial", "contoso", FINANCE, make_report("groundedness", judge_config_id="alt-judge")
    )
    got = [
        (r.judge_config_id, r.dimension) for r in await store.calibrations(make_scope(), FINANCE)
    ]
    assert got == [
        (None, "groundedness"),
        ("alt-judge", "groundedness"),
        ("judge", "groundedness"),
        ("judge", "safety"),
    ]


async def check_drift_alerts_scoped_filtered_and_ordered(store: EvaluationStore) -> None:
    late = make_alert("2026-10-19T00:00:00Z", "safety")
    early = make_alert("2026-10-18T00:00:00Z", "groundedness")
    await store.put_drift_alert("commercial", "contoso", FINANCE, late)
    await store.put_drift_alert("commercial", "contoso", FINANCE, early)
    await store.put_drift_alert("commercial", "contoso", FINANCE, early)  # same key: no duplicate
    await store.put_drift_alert("commercial", "contoso", OPERATIONS, late)
    await store.put_drift_alert("commercial", "fabrikam", FABRIKAM_FINANCE, late)
    scope = make_scope()
    assert await store.drift_alerts(scope, FINANCE) == (early, late)
    assert await store.drift_alerts(scope, FINANCE, subject_id=AGENT) == (early, late)
    assert await store.drift_alerts(scope, FINANCE, subject_id="x") == ()
    assert await store.drift_alerts(scope, OPERATIONS) == ()  # not allowed for this scope
    assert await store.drift_alerts(scope, FABRIKAM_FINANCE) == ()


async def check_coverage_latest_per_stratum_and_scoped(store: EvaluationStore) -> None:
    later = T + timedelta(days=1)
    await store.put_coverage(make_cov("run1", "agent-a", 5, T))
    await store.put_coverage(make_cov("run2", "agent-a", 9, later))
    await store.put_coverage(make_cov("run2", "agent-b", 2, later))
    await store.put_coverage(make_cov("run2", "agent-b", 3, later))  # same key: upsert
    await store.put_coverage(make_cov("run1", "agent-c", 7, T, domain=OPERATIONS))
    await store.put_coverage(
        make_cov("run1", "agent-z", 1, T, customer="fabrikam", domain=FABRIKAM_FINANCE)
    )
    got = await store.coverage(make_scope(), FINANCE)
    assert [(c.stratum, c.sampled, c.population) for c in got] == [
        ("agent-a", 9, None),
        ("agent-b", 3, None),
    ]
    assert await store.coverage(make_scope(), OPERATIONS) == ()
    assert await store.coverage(make_scope(), FABRIKAM_FINANCE) == ()


async def check_coverage_keeps_unknown_as_none(store: EvaluationStore) -> None:
    await store.put_coverage(make_cov("run1", "agent-a", 0, T, population=None))
    await store.put_coverage(make_cov("run1", "agent-b", 4, T, population=10))
    got = await store.coverage(make_scope(), FINANCE)
    assert [(c.stratum, c.sampled, c.population) for c in got] == [
        ("agent-a", 0, None),
        ("agent-b", 4, 10),
    ]


CHECKS: dict[str, Check] = {
    name.removeprefix("check_"): fn
    for name, fn in sorted(globals().items())
    if name.startswith("check_")
}
