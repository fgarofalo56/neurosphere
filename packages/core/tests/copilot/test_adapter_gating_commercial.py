"""Commercial copilot gating against the shipped matrix (gpt-4.1-mini rows, observed 2026-11-11)."""

from __future__ import annotations

import pytest
from neurosphere_core.copilot.models import AdapterConfig, resolve_adapters

COM_ENDPOINT = "https://ns-test.openai.azure.com"
GLOBAL_STANDARD = "Global Standard"
DATA_ZONE = "Data Zone Standard"


def _approved(cloud: str, region: str, sku: str, endpoint: str = COM_ENDPOINT):
    config = AdapterConfig(
        kind="approved_endpoint",
        endpoint=endpoint,
        deployment="mini",
        model_feature="model_gpt_4_1_mini",
        sku=sku,
    )
    entries = resolve_adapters(cloud=cloud, region=region, configs=[config])  # type: ignore[arg-type]
    return next(e for e in entries if e.kind == "approved_endpoint")


def test_centralus_global_standard_is_enabled() -> None:
    entry = _approved("commercial", "centralus", GLOBAL_STANDARD)
    assert entry.enabled, entry.reason
    assert entry.reason_code is None


def test_westus3_data_zone_standard_is_enabled() -> None:
    assert _approved("commercial", "westus3", DATA_ZONE).enabled


@pytest.mark.parametrize(
    "region",
    [
        "brazilsouth",
        "canadaeast",
        "eastus",
        "eastus2",
        "northcentralus",
        "southcentralus",
        "westus",
    ],
)
def test_other_global_standard_regions_are_enabled(region: str) -> None:
    assert _approved("commercial", region, GLOBAL_STANDARD).enabled


def test_canadacentral_global_standard_stays_disabled_with_a_reason() -> None:
    entry = _approved("commercial", "canadacentral", GLOBAL_STANDARD)
    assert not entry.enabled
    assert entry.reason_code is not None
    assert entry.reason


def test_brazilsouth_data_zone_standard_stays_disabled() -> None:
    entry = _approved("commercial", "brazilsouth", DATA_ZONE)
    assert not entry.enabled
    assert entry.reason_code is not None


def test_government_cloud_refuses_the_commercial_endpoint() -> None:
    entry = _approved("government", "usgovvirginia", DATA_ZONE)
    assert not entry.enabled
    assert entry.reason_code == "endpoint_cloud_mismatch"
