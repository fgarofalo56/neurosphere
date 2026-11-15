"""PRP-46 (#148 item 2): resource group hardening and optional-list degradation."""

from __future__ import annotations

import pytest
from neurosphere_core.gateway import PollAttribution, normalize_arm_id

_BASE = "/subscriptions/11111111-2222-4333-8444-555555555555/resourceGroups/{rg}"
_TAIL = "/providers/Microsoft.ApiManagement/service/apim-demo"


@pytest.mark.parametrize("group", [".", "..", "rg-x.", "rg.."])
def test_bad_resource_groups_are_refused(group: str) -> None:
    with pytest.raises(ValueError):
        normalize_arm_id(_BASE.format(rg=group) + _TAIL)


@pytest.mark.parametrize("group", ["rg-apim", "rg.a", "rg_(1)"])
def test_good_resource_groups_pass(group: str) -> None:
    arm_id = _BASE.format(rg=group) + _TAIL
    assert normalize_arm_id(arm_id) == arm_id


def test_poll_attribution_defaults() -> None:
    assert PollAttribution().model_dump() == {
        "attributed_row": 0,
        "attributed_exact": 0,
        "attributed_subscription_only": 0,
        "unattributed": 0,
        "metrics_query_failed": False,
    }
