"""PRP-16 item 10: the ``evaluation`` role's judge selection and offline pilot + calibration stage.

Real in-memory HITL service, evaluation store, calibration and ``run_pipeline``; the judge is the
sandbox recorded-fixture judge. No network, no credential, no socket.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from azure.core.credentials_async import AsyncTokenCredential
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.evaluation.endpoint_judge import EndpointJudge
from neurosphere_core.evaluation.judge import RecordedFixtureJudge
from neurosphere_core.evaluation.registry import check_result_references
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_workers.evaluation.labels import DISPUTE_KIND
from neurosphere_workers.runtime import RoleConfigError
from neurosphere_workers.runtime.factories import (
    RuntimeConfig,
    _evaluation_judge,  # pyright: ignore[reportPrivateUsage]
    _OfflineEvaluation,  # pyright: ignore[reportPrivateUsage]
    _pilot_datasets,  # pyright: ignore[reportPrivateUsage]
    build_evaluation,
)
from neurosphere_workers.runtime.settings import (
    AuthSettings,
    EvalSettings,
    StoreSettings,
    WorkerSettings,
)

_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation_worker.test_hitl_labels import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    build_hitl,
    decide,
    make_scope,
)

from sandbox.evaluation.build import DATA_DIR  # noqa: E402
from sandbox.evaluation.loader import (  # noqa: E402
    PILOT_DATASET_ID,
    load_fixture_judge,
    load_registry,
)

DOMAIN = "government:sandbox:neurosphere:domain:sbx-dom"
SUBJECT = "government:sandbox:foundry:agent:sbx-agent"
T0 = datetime(2026, 11, 9, 9, 0, 0, tzinfo=UTC)
GOV_ENDPOINT = "https://judge-acct.openai.azure.us"
COMM_ENDPOINT = "https://judge-acct.openai.azure.com"


def _cfg(cloud: str) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="dev", cloud=cloud),  # type: ignore[arg-type]
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id="sandbox"),
    )


def _settings(**overrides: Any) -> EvalSettings:
    base: dict[str, Any] = {
        "data_dir": DATA_DIR,
        "judge_config_id": "sbx-judge-government",
        "pilot_dataset_ids": PILOT_DATASET_ID,
        "pilot_domain_id": DOMAIN,
        "pilot_subject_id": SUBJECT,
        "calibration_sample_cap": 30,
    }
    base.update(overrides)
    return EvalSettings(**base)


class _CheckedStore(InMemoryEvaluationStore):
    """Pins criterion 1: every result the role stores passed ``check_result_references``."""

    def __init__(self, registry: Any) -> None:
        super().__init__()
        self._registry = registry
        self.checked = 0

    async def put_result(self, result: EvaluationResult) -> None:  # type: ignore[override]
        check_result_references(result, self._registry)
        self.checked += 1
        await super().put_result(result)


class _Clock:
    def __init__(self) -> None:
        self._now = T0

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


def _offline(settings: EvalSettings | None = None) -> tuple[_OfflineEvaluation, _CheckedStore, Any]:
    ev = settings or _settings()
    registry = load_registry()
    rubric = registry.rubrics.get(ev.rubric_id, ev.rubric_version)
    config = registry.judge_configs.get(ev.judge_config_id, ev.judge_config_version)
    assert rubric is not None and config is not None
    store = _CheckedStore(registry)
    hitl = build_hitl()
    offline = _OfflineEvaluation(
        registry=registry,
        rubric=rubric,
        judge_config=config,
        judge=load_fixture_judge(),
        store=store,
        hitl=hitl,
        datasets=tuple(_pilot_datasets(registry, ev)),
        settings=ev,
        customer_id="sandbox",
        cloud="government",
        clock=_Clock(),
    )
    return offline, store, hitl


def _scope(*domains: str) -> Any:
    return make_scope(*(domains or (DOMAIN,)), cloud="government", customer="sandbox")


async def _dispute_ids(hitl: Any, scope: Any) -> list[str]:
    items = (await hitl.store.list(scope, DOMAIN, kind=DISPUTE_KIND)).items
    return [i.item_id for i in sorted(items, key=lambda i: i.item_id)]


async def test_llm_judge_stays_uncalibrated_until_labels_reach_the_minimum() -> None:
    offline, store, hitl = _offline()
    scope = _scope()

    (first,) = await offline.run(scope)
    # No labels yet: the LLM judge emits no result, but the label loop opened a sample.
    assert first.results_stored == 0
    assert first.calibrations_stored == 0
    assert first.uncalibrated_judges
    opened = await _dispute_ids(hitl, scope)
    assert len(opened) == 30
    # Item 14 wiring: every opened review item has its calibration context recorded.
    items = (await hitl.store.list(scope, DOMAIN, kind=DISPUTE_KIND)).items
    for item in items:
        sample = await store.get_calibration_sample(scope, DOMAIN, item.subject_ref)
        assert sample is not None and sample.dataset_id is not None

    # Below the minimum (20): still uncalibrated, no pilot results, no matter the label count.
    for item_id in opened[:19]:
        await decide(hitl, item_id, "rejected", at=T0 + timedelta(hours=1))
    (second,) = await offline.run(scope)
    assert second.results_stored == 0
    assert await store.results(scope, DOMAIN, SUBJECT) == ()
    assert await _dispute_ids(hitl, scope) == opened  # re-running opens nothing new

    # At the minimum the judge is calibrated: results and a calibration report are stored.
    await decide(hitl, opened[19], "approved", at=T0 + timedelta(hours=2))
    (third,) = await offline.run(scope)
    assert third.calibrations_stored == 1
    assert third.results_stored > 0
    assert not third.uncalibrated_judges
    stored = await store.results(scope, DOMAIN, SUBJECT)
    assert len(stored) == third.results_stored
    assert len(await store.calibrations(scope, DOMAIN)) == 1
    # Criterion 1: every stored result passed the registry reference check.
    assert store.checked == third.results_stored


async def test_pilot_domain_must_be_inside_the_workers_scope() -> None:
    offline, store, _hitl = _offline()
    other = "government:sandbox:neurosphere:domain:other"
    with pytest.raises(RoleConfigError) as caught:
        await offline.run(_scope(other))
    assert caught.value.reason == "evaluation_pilot_domain_out_of_scope"
    assert store.checked == 0


async def test_pilot_customer_must_match_the_scope() -> None:
    offline, _store, _hitl = _offline()
    foreign = make_scope(DOMAIN, cloud="government", customer="someone-else")
    with pytest.raises(RoleConfigError) as caught:
        await offline.run(foreign)
    assert caught.value.reason == "evaluation_pilot_domain_out_of_scope"


def test_pilot_misconfiguration_fails_the_build() -> None:
    registry = load_registry()
    assert _pilot_datasets(registry, _settings(pilot_dataset_ids="")) == []
    with pytest.raises(RoleConfigError) as no_domain:
        _pilot_datasets(registry, _settings(pilot_domain_id=" "))
    assert no_domain.value.reason == "evaluation_pilot_domain_missing"
    with pytest.raises(RoleConfigError) as no_subject:
        _pilot_datasets(registry, _settings(pilot_subject_id=None))
    assert no_subject.value.reason == "evaluation_pilot_subject_missing"
    with pytest.raises(RoleConfigError) as unknown:
        _pilot_datasets(registry, _settings(pilot_dataset_ids="no-such-dataset"))
    assert unknown.value.reason == "evaluation_pilot_dataset_unregistered"


def _credential_must_not_be_built() -> AsyncTokenCredential:
    raise AssertionError("the credential is only built when the endpoint judge is selected")


def _stub_credential() -> AsyncTokenCredential:
    return object()  # type: ignore[return-value]  # never asked for a token: no request is made


def _judge(cfg: RuntimeConfig, ev: EvalSettings, cred: Callable[[], AsyncTokenCredential]) -> Any:
    return _evaluation_judge(cfg, ev, DATA_DIR, cred)


def test_fixture_judge_is_the_default_and_builds_no_credential() -> None:
    judge = _judge(_cfg("government"), _settings(), _credential_must_not_be_built)
    assert isinstance(judge, RecordedFixtureJudge)


def test_endpoint_judge_builds_for_the_deployment_cloud_without_network() -> None:
    ev = _settings(judge="endpoint", judge_endpoint=GOV_ENDPOINT, judge_deployment="judge-1")
    assert isinstance(_judge(_cfg("government"), ev, _stub_credential), EndpointJudge)
    ev = _settings(judge="endpoint", judge_endpoint=COMM_ENDPOINT, judge_deployment="judge-1")
    assert isinstance(_judge(_cfg("commercial"), ev, _stub_credential), EndpointJudge)


@pytest.mark.parametrize(
    ("cloud", "endpoint", "deployment", "reason"),
    [
        ("government", COMM_ENDPOINT, "judge-1", "evaluation_judge_endpoint_cloud_mismatch"),
        ("commercial", GOV_ENDPOINT, "judge-1", "evaluation_judge_endpoint_cloud_mismatch"),
        ("government", None, "judge-1", "evaluation_judge_endpoint_missing"),
        ("government", "http://x.openai.azure.us", "judge-1", "evaluation_judge_endpoint_invalid"),
        ("government", GOV_ENDPOINT, None, "evaluation_judge_deployment_missing"),
        ("government", GOV_ENDPOINT, "bad name!", "evaluation_judge_config_invalid"),
    ],
)
def test_endpoint_judge_fails_closed(
    cloud: str, endpoint: str | None, deployment: str | None, reason: str
) -> None:
    ev = _settings(judge="endpoint", judge_endpoint=endpoint, judge_deployment=deployment)
    with pytest.raises(RoleConfigError) as caught:
        _judge(_cfg(cloud), ev, _stub_credential)
    assert caught.value.reason == reason


async def test_build_refuses_a_wrong_cloud_endpoint_and_a_missing_pilot_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_WORKER_EVAL_DATA_DIR", str(DATA_DIR))
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE_CONFIG_ID", "sbx-judge-government")
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE", "endpoint")
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE_ENDPOINT", COMM_ENDPOINT)
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE_DEPLOYMENT", "judge-1")
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_evaluation(_cfg("government"), lifetime)
    assert caught.value.reason == "evaluation_judge_endpoint_cloud_mismatch"

    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE", "fixture")
    monkeypatch.setenv("NS_WORKER_EVAL_PILOT_DATASET_IDS", PILOT_DATASET_ID)
    monkeypatch.delenv("NS_WORKER_EVAL_PILOT_DOMAIN_ID", raising=False)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as missing:
            await build_evaluation(_cfg("government"), lifetime)
    assert missing.value.reason == "evaluation_pilot_domain_missing"
