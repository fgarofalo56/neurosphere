"""PRP-59 item 4: copilot gating applies the Government region allowlist (#212)."""

from __future__ import annotations

import pytest
from neurosphere_core.copilot.models import AdapterConfig, resolve_adapters

GOV_ENDPOINT = "https://ns-test.openai.azure.us"


def _gov(region: str):
    config = AdapterConfig(
        kind="approved_endpoint",
        endpoint=GOV_ENDPOINT,
        deployment="gpt-4o",
        model_feature="model_gpt_4o",
        sku="Data Zone Standard",
    )
    entries = resolve_adapters(cloud="government", region=region, configs=[config])
    return next(e for e in entries if e.kind == "approved_endpoint")


@pytest.mark.parametrize("region", ["usdodeast", "usdodcentral", "", "US Gov!", "eastus"])
def test_non_deployable_government_region_is_disabled_not_raised(region: str) -> None:
    entry = _gov(region)
    assert not entry.enabled
    assert entry.reason_code == "capability_unavailable"
    assert entry.reason


def test_deployable_government_region_still_resolves() -> None:
    entry = _gov("usgovvirginia")
    assert entry.enabled, entry.reason
