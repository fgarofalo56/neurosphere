"""PRP-61 item 4: the detections role idles unconfigured, refuses bad config, one tick stores."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_core.detections import (
    AccountRead,
    AiAccount,
    CatalogRead,
    ContentFilterRule,
    DeploymentConfig,
    DeploymentConfigRead,
    GatewayFragmentRule,
    GatewayFragments,
    GatewayRead,
    ShadowAiRule,
)
from neurosphere_core.detections.fakes import (
    FakeAiAccountInventory,
    FakeCatalogDeploymentReader,
    FakeDeploymentConfigReader,
    FakeGatewayInventoryReader,
)
from neurosphere_core.recommendations.store import InMemoryRecommendationStore
from neurosphere_workers.detections.role import DetectionRunner, build_detections
from neurosphere_workers.runtime import RoleConfigError, parse_roles
from neurosphere_workers.runtime.adapters import WorkerRole
from neurosphere_workers.runtime.factories import BUILDERS, RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .support import DOMAIN, make_scope

_ENV = (
    "NS_WORKER_DETECT_ENABLED",
    "NS_WORKER_DETECT_DOMAIN_ID",
    "NS_WORKER_DETECT_INTERVAL_SECONDS",
    "NS_WORKER_DETECT_FOUNDRY_ACCOUNTS",
    "NS_WORKER_DETECT_ACCEPTABLE_RAI_POLICIES",
    "NS_WORKER_DETECT_REQUIRED_APIM_FRAGMENTS",
    "NS_WORKER_DETECT_SUBSCRIPTIONS",
    "NS_WORKER_DETECT_MAX_ITEMS",
)
SUB = "11111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _config() -> RuntimeConfig:
    return RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(f"NS_WORKER_DETECT_{key}", value)


async def _reason(monkeypatch: pytest.MonkeyPatch, **values: str) -> str:
    _env(monkeypatch, **values)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_detections(_config(), lifetime)
    return caught.value.reason


def test_role_is_in_all_and_registered() -> None:
    assert "detections" in parse_roles("all")
    assert BUILDERS["detections"] is build_detections


async def test_unconfigured_role_idles_with_one_info_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _env(monkeypatch)
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            role = await build_detections(_config(), lifetime)
    assert isinstance(role, WorkerRole)
    events = [getattr(r, "event", None) for r in caplog.records]
    assert events.count("worker.detections_unconfigured") == 1


async def test_settings_without_enabled_still_idle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _env(monkeypatch, REQUIRED_APIM_FRAGMENTS="pii-redact")
    with caplog.at_level(logging.INFO):
        async with ClientLifetime() as lifetime:
            assert isinstance(await build_detections(_config(), lifetime), WorkerRole)
    assert "worker.detections_unconfigured" in [getattr(r, "event", None) for r in caplog.records]


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ({"ENABLED": "1"}, "detections_domain_id_missing"),
        ({"ENABLED": "1", "DOMAIN_ID": "d1"}, "detections_domain_id_invalid"),
        ({"ENABLED": "1", "DOMAIN_ID": DOMAIN}, "detections_no_rules_configured"),
        (
            {"ENABLED": "1", "DOMAIN_ID": DOMAIN, "FOUNDRY_ACCOUNTS": "nope"},
            "detections_foundry_accounts_invalid",
        ),
        (
            {
                "ENABLED": "1",
                "DOMAIN_ID": DOMAIN,
                "FOUNDRY_ACCOUNTS": f"government:{SUB}/rg/a/usgovvirginia",
            },
            "detections_account_cloud_mismatch",
        ),
        (
            {"ENABLED": "1", "DOMAIN_ID": DOMAIN, "SUBSCRIPTIONS": f"government:{SUB}"},
            "detections_subscription_cloud_mismatch",
        ),
        (
            {"ENABLED": "1", "DOMAIN_ID": DOMAIN, "SUBSCRIPTIONS": "not-a-guid"},
            "detections_subscriptions_invalid",
        ),
        (
            {"ENABLED": "1", "DOMAIN_ID": DOMAIN, "REQUIRED_APIM_FRAGMENTS": "<bad>"},
            "detections_fragments_invalid",
        ),
        (
            {
                "ENABLED": "1",
                "DOMAIN_ID": DOMAIN,
                "SUBSCRIPTIONS": SUB,
                "ACCEPTABLE_RAI_POLICIES": "bad;name",
            },
            "detections_rai_policies_invalid",
        ),
    ],
)
async def test_bad_configuration_fails_the_role_with_a_reason(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, str], reason: str
) -> None:
    assert await _reason(monkeypatch, **values) == reason


async def test_one_tick_with_fakes_stores_findings_and_logs_counts_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryRecommendationStore()
    rules = [
        ContentFilterRule(
            cloud="commercial",
            customer_id="contoso",
            reader=FakeDeploymentConfigReader(
                [
                    DeploymentConfigRead(
                        "acct-1",
                        deployments=(DeploymentConfig("acct-1", "secret-looking-name", None),),
                    )
                ]
            ),
        ),
        GatewayFragmentRule(
            cloud="commercial",
            customer_id="contoso",
            reader=FakeGatewayInventoryReader(
                GatewayRead(gateways=(GatewayFragments("gw-aaaa", frozenset()),))
            ),
            required_fragments=("pii-redact",),
        ),
        ShadowAiRule(
            cloud="commercial",
            customer_id="contoso",
            inventory=FakeAiAccountInventory(
                AccountRead(accounts=(AiAccount("rogue", "/subscriptions/x/rogue", "eastus", "s"),))
            ),
            catalog=FakeCatalogDeploymentReader(CatalogRead()),
        ),
    ]
    runner = DetectionRunner(
        rules=rules,
        store=store,
        cloud="commercial",
        customer_id="contoso",
        domain_id=DOMAIN,
        interval_seconds=900.0,
        clock=lambda: NOW,
    )
    with caplog.at_level(logging.DEBUG):
        summary = await runner.tick()
        again = await runner.tick()
    assert summary.stored == 3 and again.stored == 3
    assert summary.coverage["detect.gateway_policy_fragment"] == "full"
    page = await store.list(make_scope([DOMAIN]), DOMAIN, limit=50)
    assert len(page.items) == 3  # same ids on the second tick: no duplicates
    assert {r.kind for r in page.items} == {"configuration_finding", "unregistered_ai_resource"}
    log_text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "secret-looking-name" not in log_text and "rogue" not in log_text


async def test_a_failing_rule_does_not_stop_the_others() -> None:
    store = InMemoryRecommendationStore()
    broken = FakeAiAccountInventory()
    broken.error = RuntimeError("boom")
    # A broken reader is reported inside the rule (unknown), never raised to the runner.
    good = ContentFilterRule(
        cloud="commercial",
        customer_id="contoso",
        reader=FakeDeploymentConfigReader(
            [DeploymentConfigRead("a", deployments=(DeploymentConfig("a", "dep", None),))]
        ),
    )
    shadow = ShadowAiRule(
        cloud="commercial",
        customer_id="contoso",
        inventory=broken,
        catalog=FakeCatalogDeploymentReader(),
    )
    runner = DetectionRunner(
        rules=[shadow, good],
        store=store,
        cloud="commercial",
        customer_id="contoso",
        domain_id=DOMAIN,
        interval_seconds=900.0,
        clock=lambda: NOW,
    )
    summary = await runner.tick()
    assert summary.stored == 1
    assert summary.coverage["detect.shadow_ai_account"] == "unknown"
