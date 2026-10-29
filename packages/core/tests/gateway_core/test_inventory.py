"""ARM preflight and inventory against a fake ARM: paging, 429, pool backends, diagnostics."""

from __future__ import annotations

import json

import httpx
import pytest
from neurosphere_core.clients import arm_client
from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.gateway import inventory as inventory_module
from neurosphere_core.gateway import preflight, read_inventory

from .fake_arm import RID, SECRET_MARKER, XML_MARKER, FakeArm, FakeCredential

COMMERCIAL = profile_for(CloudName.COMMERCIAL)
GOVERNMENT = profile_for(CloudName.GOVERNMENT)


def _client(fake: FakeArm, profile=COMMERCIAL) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return arm_client(profile, FakeCredential(), transport=fake.transport())  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(inventory_module, "_sleep", fake_sleep)
    return slept


@pytest.mark.parametrize(
    ("sku", "tier"),
    [
        ("Consumption", "consumption"),
        ("Developer", "developer"),
        ("Basic", "basic"),
        ("Standard", "standard"),
        ("Premium", "premium"),
        ("BasicV2", "basic_v2"),
        ("StandardV2", "standard_v2"),
        ("PremiumV2", "premium_v2"),
        ("Isolated", "unknown"),
    ],
)
async def test_preflight_maps_sku_to_tier(sku: str, tier: str) -> None:
    async with _client(FakeArm(sku=sku)) as client:
        result = await preflight(client, RID, profile=COMMERCIAL)
    assert result.tier == tier
    assert result.sku_name_raw == sku
    assert result.name == "apim-demo"


async def test_preflight_diagnostics_with_llm_logs() -> None:
    async with _client(FakeArm(llm_logs=True, mcp_logs=False)) as client:
        result = await preflight(client, RID)
    d = result.diagnostics
    assert (d.gateway_logs, d.gateway_llm_logs, d.gateway_mcp_logs) == (True, True, False)
    assert d.workspace_resource_id is not None
    assert d.workspace_resource_id.endswith("/workspaces/law-demo")


async def test_preflight_diagnostics_without_llm_logs() -> None:
    async with _client(FakeArm(llm_logs=False)) as client:
        d = (await preflight(client, RID)).diagnostics
    assert d.gateway_logs is True
    assert d.gateway_llm_logs is False


async def test_category_group_all_logs_enables_everything() -> None:
    async with _client(FakeArm(llm_logs=False, diag_category_group="allLogs")) as client:
        d = (await preflight(client, RID)).diagnostics
    assert d.gateway_logs and d.gateway_llm_logs and d.gateway_mcp_logs


async def test_service_not_found_is_not_readable() -> None:
    async with _client(FakeArm(service_status=404)) as client:
        with pytest.raises(CapabilityUnavailableError) as info:
            await preflight(client, RID)
    assert info.value.reason == "gateway_not_readable"


async def test_inventory_follows_next_link_and_maps_everything() -> None:
    fake = FakeArm()
    async with _client(fake) as client:
        inv = await read_inventory(client, RID, profile=COMMERCIAL, gateway_id="gw-" + "0" * 32)
    assert [a.id for a in inv.apis] == ["chat", "tools"]
    assert inv.apis[0].path == "openai"
    assert inv.apis[0].subscription_required is True
    assert [(o.api_id, o.id, o.method) for o in inv.operations] == [("chat", "completions", "POST")]
    assert [(p.id, p.state) for p in inv.products] == [("starter", "published")]
    assert [(link.product_id, link.api_id) for link in inv.product_api_links] == [
        ("starter", "chat")
    ]
    assert [f.name for f in inv.policy_fragments] == ["frag-1"]
    assert [(s.id, s.state) for s in inv.subscriptions] == [("sub-1", "active")]


async def test_pool_backend_and_circuit_breaker() -> None:
    async with _client(FakeArm()) as client:
        inv = await read_inventory(client, RID, gateway_id="gw-" + "0" * 32)
    single, pool = inv.backends
    assert single.type == "Single"
    assert single.url == "https://east.openai.azure.com/openai"
    rule = single.circuit_breaker_rules[0]
    assert (rule.name, rule.trip_duration, rule.failure_count) == ("trip-on-429", "PT1M", 3)
    assert rule.failure_interval == "PT10S"
    assert rule.status_codes == ["429", "500-599"]
    assert pool.type == "Pool"
    assert pool.url is None
    assert [(m.backend_id, m.weight, m.priority) for m in pool.pool_members] == [
        ("foundry-east", 3, 1),
        ("foundry-west", 1, 2),
    ]


async def test_secrets_and_policy_bodies_never_reach_the_snapshot() -> None:
    async with _client(FakeArm()) as client:
        inv = await read_inventory(client, RID, gateway_id="gw-" + "0" * 32)
    dumped = json.dumps(inv.model_dump(mode="json"))
    assert SECRET_MARKER not in dumped
    assert XML_MARKER not in dumped
    assert "<policies" not in dumped


async def test_429_honours_retry_after_then_succeeds(_no_sleep: list[float]) -> None:
    fake = FakeArm(throttle=2)
    async with _client(fake) as client:
        inv = await read_inventory(client, RID, gateway_id="gw-" + "0" * 32)
    assert len(inv.apis) == 2
    assert len(_no_sleep) == 2
    assert all(0 < s <= 30 for s in _no_sleep)


async def test_429_exhausted_maps_to_dependency_transient(_no_sleep: list[float]) -> None:
    fake = FakeArm(throttle_forever=True)
    async with _client(fake) as client:
        with pytest.raises(DependencyTransientError) as info:
            await preflight(client, RID)
    assert info.value.reason == "arm_rate_limited"
    assert info.value.retry_after_seconds is not None
    assert len(_no_sleep) == inventory_module.MAX_RETRIES
    assert len(fake.requests) == inventory_module.MAX_RETRIES + 1


async def test_government_profile_rejects_commercial_host() -> None:
    gov_client = arm_client(GOVERNMENT, FakeCredential(), transport=FakeArm().transport())  # type: ignore[arg-type]
    commercial_client = _client(FakeArm())
    async with gov_client, commercial_client:
        # A Government profile refuses a client bound to the Commercial ARM host...
        with pytest.raises(CapabilityUnavailableError) as info:
            await read_inventory(commercial_client, RID, profile=GOVERNMENT)
        assert info.value.reason == "endpoint_cloud_mismatch"
    # ...and a Government client refuses a nextLink that points at the Commercial host.
    fake = FakeArm(next_link_host="management.azure.com")
    async with arm_client(GOVERNMENT, FakeCredential(), transport=fake.transport()) as client:  # type: ignore[arg-type]
        with pytest.raises(CapabilityUnavailableError):
            await read_inventory(client, RID, profile=GOVERNMENT)
    assert all(r.url.host != "management.azure.com" for r in fake.requests)


async def test_bad_resource_id_is_rejected_before_any_request() -> None:
    fake = FakeArm()
    async with _client(fake) as client:
        with pytest.raises(ValueError, match="resource id"):
            await read_inventory(client, "/subscriptions/x/resourceGroups/y")
    assert fake.requests == []


async def test_read_only_no_secret_listing() -> None:
    """Security: only GET requests, never a ``listSecrets``/``listKeys`` path."""
    fake = FakeArm()
    async with _client(fake) as client:
        await preflight(client, RID)
        await read_inventory(client, RID, gateway_id="gw-" + "0" * 32)
    assert fake.requests
    assert fake.methods == {"GET"}
    lowered = [p.lower() for p in fake.paths]
    assert not any("listsecrets" in p or "listkeys" in p or "namedvalues" in p for p in lowered)
