"""PRP-59 item 4: a DoD region is not a deployable Government region for Fabric (#212)."""

from __future__ import annotations

import pytest
from neurosphere_core.cloud import CloudName
from neurosphere_workers.actions.deploy import fabric_unavailable_reason


@pytest.mark.parametrize("region", ["usdodeast", "usdodcentral"])
def test_dod_region_is_invalid_for_government(region: str) -> None:
    assert fabric_unavailable_reason(CloudName.GOVERNMENT, region) == "invalid_region"
