"""Runtime Government region allowlist equals the sovereign profile record (PRP-20 item 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from neurosphere_core.capabilities.validate import (
    GOVERNMENT_DEPLOYABLE_REGIONS,
    DeploymentProfile,
)

_PROFILE = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "bicep"
    / "params"
    / "government"
    / "sovereign-profile.yaml"
)


def _profile(region: str) -> DeploymentProfile:
    return DeploymentProfile(
        cloud="government",
        regions=(region,),
        hosting="aks",
        analytics="fabric",
    )


def test_runtime_set_equals_sovereign_profile_allowed_regions() -> None:
    doc = yaml.safe_load(_PROFILE.read_text(encoding="utf-8"))
    names = {r["name"] for r in doc["allowedRegions"]}
    assert names == set(GOVERNMENT_DEPLOYABLE_REGIONS)


@pytest.mark.parametrize("region", sorted(GOVERNMENT_DEPLOYABLE_REGIONS))
def test_allowed_region_validates(region: str) -> None:
    assert _profile(region).regions == (region,)


@pytest.mark.parametrize("region", ["usdodeast", "usdodcentral", "usgovfoo"])
def test_other_gov_regions_refused(region: str) -> None:
    with pytest.raises(ValueError, match="capability_unavailable") as exc:
        _profile(region)
    assert "usgovvirginia" in str(exc.value)
