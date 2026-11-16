"""PRP-45 item 5: the ``evaluation`` role builds its judge from a stored ``judge`` setting.

The admin_config store is an in-memory twin behind the factories' Cosmos seam; no network, no
credential is ever asked for a token, no judge endpoint is called.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import SYSTEM_SETTING_KIND, document_id
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.runtime import RoleConfigError, factories
from neurosphere_workers.runtime.factories import RuntimeConfig, build_evaluation
from neurosphere_workers.runtime.settings import (
    AuthSettings,
    EvalSettings,
    StoreSettings,
    WorkerSettings,
)

_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sandbox.evaluation.build import DATA_DIR  # noqa: E402

CUSTOMER = "sandbox"
ACTOR = "government:sandbox:entra:person:p-" + "0c" * 32
GOV_ENDPOINT = "https://judge-acct.openai.azure.us"
COMM_ENDPOINT = "https://judge-acct.openai.azure.com"
MI = {
    "kind": "managed_identity",
    "managed_identity_client_id": "0b5d0c6e-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
}


def _cfg(cloud: str = "government") -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="dev", cloud=cloud),  # type: ignore[arg-type]
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id=CUSTOMER),
    )


def _judge_body(endpoint: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "setting_key": "judge",
        "enabled": enabled,
        "judge": {
            "endpoint": endpoint,
            "deployment": "judge-stored",
            "api_version": "2024-10-21",
            "resource_id": None,
            "credential": MI,
        },
    }


async def _repo(*bodies: dict[str, Any]) -> InMemoryAdminConfigRepository:
    repo = InMemoryAdminConfigRepository()  # no cloud bound: a value the deployment now refuses
    for body in bodies:
        await repo.create(
            CUSTOMER, SYSTEM_SETTING_KIND, document_id("judge"), body, updated_by=ACTOR
        )
    return repo


class _CapturedError(Exception):
    def __init__(self, evaluation: EvalSettings) -> None:
        super().__init__("captured")
        self.evaluation = evaluation


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NS_WORKER_EVAL_JUDGE_ENDPOINT", "NS_WORKER_EVAL_JUDGE_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_WORKER_EVAL_DATA_DIR", str(DATA_DIR))
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE_CONFIG_ID", "sbx-judge-government")
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE", "fixture")


def _store(monkeypatch: pytest.MonkeyPatch, repo: Any) -> None:
    monkeypatch.setattr(factories, "create_cosmos_client", lambda *a, **k: object())

    class _Repo:
        @staticmethod
        def from_client(*args: Any, **kwargs: Any) -> Any:
            return repo

    monkeypatch.setattr(factories, "CosmosAdminConfigRepository", _Repo)


def _capture(monkeypatch: pytest.MonkeyPatch) -> None:
    def judge(cfg: Any, evaluation: EvalSettings, *args: Any) -> Any:
        raise _CapturedError(evaluation)

    monkeypatch.setattr(factories, "_evaluation_judge", judge)


async def _build(cfg: RuntimeConfig) -> None:
    async with ClientLifetime() as lifetime:
        await build_evaluation(cfg, lifetime)


async def test_a_stored_judge_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch, await _repo(_judge_body(GOV_ENDPOINT)))
    _capture(monkeypatch)
    with pytest.raises(_CapturedError) as caught:
        await _build(_cfg())
    evaluation = caught.value.evaluation
    assert evaluation.judge == "endpoint"
    assert evaluation.judge_endpoint == GOV_ENDPOINT
    assert evaluation.judge_deployment == "judge-stored"
    assert evaluation.judge_config_id == "sbx-judge-government"  # the rest stays env


async def test_a_disabled_stored_judge_is_the_recorded_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NS_WORKER_EVAL_JUDGE", "endpoint")
    _store(monkeypatch, await _repo(_judge_body(GOV_ENDPOINT, enabled=False)))
    _capture(monkeypatch)
    with pytest.raises(_CapturedError) as caught:
        await _build(_cfg())
    assert caught.value.evaluation.judge == "fixture"


async def test_a_commercial_judge_in_government_fails_the_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, await _repo(_judge_body(COMM_ENDPOINT)))
    with pytest.raises(RoleConfigError) as caught:
        await _build(_cfg("government"))
    assert caught.value.reason == "evaluation_judge_endpoint_cloud_mismatch"


async def test_a_store_outage_keeps_env(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = await _repo(_judge_body(GOV_ENDPOINT))
    repo.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    _store(monkeypatch, repo)
    _capture(monkeypatch)
    with pytest.raises(_CapturedError) as caught:
        await _build(_cfg())
    assert caught.value.evaluation.judge == "fixture"


async def test_no_store_configured_keeps_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch)  # the real Cosmos seam: no account outside local, so no store
    with pytest.raises(_CapturedError) as caught:
        await _build(_cfg())
    assert caught.value.evaluation.judge == "fixture"
