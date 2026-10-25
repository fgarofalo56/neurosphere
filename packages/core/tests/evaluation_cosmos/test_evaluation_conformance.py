"""EvaluationStore conformance: in-memory and CosmosEvaluationStore on fake containers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_core.evaluation import cosmos_store
from neurosphere_core.evaluation.cosmos_store import (
    DEFAULT_RESULTS_CONTAINER,
    DEFAULT_RUNS_CONTAINER,
    EVALUATION_PARTITION_KEY_PATHS,
    CosmosEvaluationStore,
)
from neurosphere_core.evaluation.store import EvaluationStore, InMemoryEvaluationStore

from .conformance import (
    CHECKS,
    FINANCE,
    OPERATIONS,
    T,
    make_alert,
    make_cov,
    make_report,
    make_result,
    make_scope,
    other_customer_result,
)
from .cosmos_fake import new_container
from .fake_container import FakeContainer


def _cosmos() -> CosmosEvaluationStore:
    return CosmosEvaluationStore(new_container(), new_container())  # type: ignore[arg-type]


BACKENDS: dict[str, Callable[[], EvaluationStore]] = {
    "memory": InMemoryEvaluationStore,
    "cosmos-fake": _cosmos,
}


@pytest.mark.parametrize("backend", sorted(BACKENDS))
@pytest.mark.parametrize("check", sorted(CHECKS))
async def test_conformance(backend: str, check: str) -> None:
    await CHECKS[check](BACKENDS[backend]())


def test_container_constants_match_the_wire_contract() -> None:
    assert DEFAULT_RESULTS_CONTAINER == "evaluation_results"
    assert DEFAULT_RUNS_CONTAINER == "evaluation_runs"
    assert EVALUATION_PARTITION_KEY_PATHS == ("/customer_id", "/domain_id")


# -- Cosmos-specific ----------------------------------------------------------------------------


def _pair() -> tuple[FakeContainer, FakeContainer, CosmosEvaluationStore]:
    results, runs = new_container(), new_container()
    return results, runs, CosmosEvaluationStore(results, runs)  # type: ignore[arg-type]


async def test_every_query_is_single_partition_and_carries_the_scope_predicates() -> None:
    results, runs, store = _pair()
    scope = make_scope()
    await store.put_result(make_result(1))
    await store.put_calibration("commercial", "contoso", FINANCE, make_report())
    await store.put_drift_alert("commercial", "contoso", FINANCE, make_alert())
    await store.put_coverage(make_cov("run1", "agent-a", 1, T))
    await store.list_results(scope, FINANCE, subject_id="s", dimension="safety", limit=3)
    await store.results(scope, FINANCE)
    await store.calibrations(scope, FINANCE)
    await store.drift_alerts(scope, FINANCE, subject_id="s")
    await store.coverage(scope, FINANCE)
    assert len(results.queries) == 2
    assert len(runs.queries) == 3
    for record in [*results.queries, *runs.queries]:
        assert record.partition_key == ("contoso", FINANCE)
        for predicate in ("c.customer_id = @customer", "c.domain_id = @domain", "c.cloud = @cloud"):
            assert predicate in record.query
        assert "TOP @limit" in record.query
        assert record.params["@customer"] == "contoso"
        assert record.params["@domain"] == FINANCE
        assert record.params["@cloud"] == "commercial"


async def test_a_domain_outside_the_scope_never_reaches_cosmos() -> None:
    results, runs, store = _pair()
    scope = make_scope()
    await store.put_result(make_result(1, domain_id=OPERATIONS))
    await store.list_results(scope, OPERATIONS)
    await store.results(scope, OPERATIONS)
    await store.calibrations(scope, OPERATIONS)
    await store.drift_alerts(scope, OPERATIONS)
    await store.coverage(scope, OPERATIONS)
    assert results.queries == []
    assert runs.queries == []


async def test_same_evaluation_id_in_two_customers_stays_separate_in_cosmos() -> None:
    _, _, store = _pair()
    await store.put_result(make_result(1))
    await store.put_result(other_customer_result(1))  # same id, other partition: no conflict
    mine = await store.results(make_scope(), FINANCE)
    assert [r.customer_id for r in mine] == ["contoso"]


async def test_results_are_bounded_and_fail_loudly_instead_of_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cosmos_store, "MAX_AGGREGATE_RESULTS", 3)
    _, _, store = _pair()
    for n in range(1, 4):
        await store.put_result(make_result(n))
    assert len(await store.results(make_scope(), FINANCE)) == 3
    await store.put_result(make_result(4))
    with pytest.raises(DependencyTransientError) as raised:
        await store.results(make_scope(), FINANCE)
    assert raised.value.reason == "evaluation_set_too_large"
    assert len((await store.list_results(make_scope(), FINANCE)).items) == 4  # paging still works


async def test_alerts_and_coverage_read_only_the_newest_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cosmos_store, "MAX_RECORDS", 2)
    _, _, store = _pair()
    for day in (1, 2, 3):
        await store.put_drift_alert(
            "commercial", "contoso", FINANCE, make_alert(f"2026-10-0{day}T00:00:00Z")
        )
    got = await store.drift_alerts(make_scope(), FINANCE)
    assert [a.detected_at for a in got] == ["2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z"]


async def test_calibration_write_retries_after_losing_an_etag_race() -> None:
    results, runs, _ = _pair()
    older = make_report(at=T - timedelta(days=1), state="uncalibrated")

    class RacingRuns(FakeContainer):
        raced = False

        async def replace_item(self, item: str, body: Any, **kwargs: Any) -> Any:
            if not self.raced:
                self.raced = True  # a concurrent writer lands between our read and replace
                await self.upsert_item(body=_doc_like(body, older))
            return await super().replace_item(item, body, **kwargs)

    def _doc_like(body: Any, report: Any) -> dict[str, Any]:
        return {**body, "body": report.model_dump(mode="json")}

    racing = RacingRuns(runs._engine.key_paths, runs._engine.clauses)  # pyright: ignore[reportPrivateUsage]
    store = CosmosEvaluationStore(results, racing)  # type: ignore[arg-type]
    await store.put_calibration(
        "commercial", "contoso", FINANCE, make_report(at=T - timedelta(days=2))
    )
    await store.put_calibration("commercial", "contoso", FINANCE, make_report(at=T))
    assert racing.raced
    (report,) = await store.calibrations(make_scope(), FINANCE)
    assert report.calibrated_at == T
    assert report.state == "calibrated"


async def test_a_tampered_document_fails_closed_as_upstream_invalid() -> None:
    results, _, store = _pair()
    await store.put_result(make_result(1))
    for doc in results.items.values():
        doc["status"] = "not_a_status"
    with pytest.raises(DependencyTransientError) as raised:
        await store.results(make_scope(), FINANCE)
    assert raised.value.reason == "evaluation_record_invalid"
    assert raised.value.status == 502


class _Failing:
    def __init__(self, status: int | None) -> None:
        self.status = status

    def _fail(self) -> Any:
        if self.status is None:
            raise ConnectionError("secret-host.example")
        raise CosmosHttpResponseError(status_code=self.status, message="boom secret")

    async def create_item(self, **_: Any) -> Any:
        self._fail()

    async def upsert_item(self, **_: Any) -> Any:
        self._fail()

    async def read_item(self, **_: Any) -> Any:
        self._fail()

    def query_items(self, *_: Any, **__: Any) -> Any:
        self._fail()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(None, DependencyTransientError), (503, DependencyTransientError), (429, RateLimitedError)],
)
async def test_outages_map_to_taxonomy_errors_without_echoing_sdk_text(
    status: int | None, expected: type[Exception]
) -> None:
    store = CosmosEvaluationStore(_Failing(status), _Failing(status))  # type: ignore[arg-type]
    scope = make_scope()
    for call in (
        store.put_result(make_result(1)),
        store.put_calibration("commercial", "contoso", FINANCE, make_report()),
        store.put_drift_alert("commercial", "contoso", FINANCE, make_alert()),
        store.put_coverage(make_cov("run1", "agent-a", 1, T)),
        store.list_results(scope, FINANCE),
        store.results(scope, FINANCE),
        store.calibrations(scope, FINANCE),
        store.drift_alerts(scope, FINANCE),
        store.coverage(scope, FINANCE),
    ):
        with pytest.raises(expected) as raised:
            await call
        assert "secret" not in str(raised.value)
