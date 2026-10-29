"""APIM gateway suffix is a frozen per-cloud profile fact."""

from __future__ import annotations

import pytest
from neurosphere_core.cloud import CloudName, CloudProfile, profile_for
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("cloud", "suffix"),
    [(CloudName.COMMERCIAL, ".azure-api.net"), (CloudName.GOVERNMENT, ".azure-api.us")],
)
def test_apim_gateway_suffix_per_cloud(cloud: CloudName, suffix: str) -> None:
    assert profile_for(cloud).apim_gateway_suffix == suffix


def test_apim_suffix_cannot_cross_clouds() -> None:
    data = profile_for(CloudName.GOVERNMENT).model_dump()
    data["apim_gateway_suffix"] = ".azure-api.net"
    with pytest.raises(ValidationError):
        CloudProfile(**data)
