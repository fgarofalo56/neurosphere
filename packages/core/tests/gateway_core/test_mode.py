"""Observe/manage mode (PRP-34 item 2): preflight evaluation, refusals, the switch, the guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway import (
    GatewayModeLookup,
    GatewayRegistration,
    InMemoryGatewayStore,
    ModePreflight,
    gateway_id_for,
)
from neurosphere_core.gateway.mode import (
    GATEWAY_APPLYING,
    GATEWAY_MANAGE_UNAVAILABLE,
    GATEWAY_NOT_REGISTERED,
    GATEWAY_OBSERVE_MODE,
    GATEWAY_PREFLIGHT_FAILED,
    MODE_TARGET_TYPE,
    MODE_UNCHANGED,
    REQUIRED_WRITE_ACTIONS,
    GatewayModeSwitch,
    ModeChange,
    evaluate_permissions,
    gateway_id_of_target,
    manage_refusal,
    mode_change_diff,
    mode_target,
    mode_target_version,
    parse_mode_change,
    require_manage,
)
from pydantic import ValidationError

from .fake_arm import RID

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
GOV_DOMAIN = "government:contoso:catalog:domain:finance"
PSEUDONYM = "pn-maker-0001"
APIM_ALL: list[dict[str, Any]] = [
    {"actions": ["Microsoft.ApiManagement/service/*"], "notActions": []}
]


def _registration(*, domain: str = DOMAIN, cloud: str = "commercial") -> GatewayRegistration:
    return GatewayRegistration(
        id=gateway_id_for(CUSTOMER, domain, RID),
        customer_id=CUSTOMER,
        domain_id=domain,
        cloud=cloud,  # type: ignore[arg-type]
        arm_resource_id=RID,
        name="apim-demo",
        tier="standard_v2",
        created_at=T0,
        updated_at=T0,
        registered_by="pn-admin",
    )


class Activity:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy
        self.asked: list[str] = []

    async def running(self, gateway_id: str) -> bool:
        self.asked.append(gateway_id)
        return self.busy


async def _switch(
    *, cloud: str = "commercial", busy: bool = False
) -> tuple[GatewayModeSwitch, InMemoryGatewayStore, GatewayRegistration, Activity]:
    domain = DOMAIN if cloud == "commercial" else GOV_DOMAIN
    store = InMemoryGatewayStore()
    saved = await store.create(_registration(domain=domain, cloud=cloud))
    activity = Activity(busy)
    switch = GatewayModeSwitch(
        store,
        customer_id=CUSTOMER,
        domain_id=domain,
        gateway_id=saved.id,
        activity=activity,
        clock=lambda: T0 + timedelta(minutes=5),
    )
    return switch, store, saved, activity


def _passed() -> ModePreflight:
    return evaluate_permissions(APIM_ALL, now=T0)


# -- preflight ------------------------------------------------------------------------------------


def test_required_actions_cover_service_and_child_writes_and_deletes() -> None:
    assert REQUIRED_WRITE_ACTIONS[0] == "Microsoft.ApiManagement/service/write"
    for kind in ("backends", "policyFragments", "apis", "products", "subscriptions"):
        assert f"Microsoft.ApiManagement/service/{kind}/write" in REQUIRED_WRITE_ACTIONS
        assert f"Microsoft.ApiManagement/service/{kind}/delete" in REQUIRED_WRITE_ACTIONS
    assert not any("listSecrets" in a for a in REQUIRED_WRITE_ACTIONS)


@pytest.mark.parametrize(
    "entries",
    [
        APIM_ALL,
        [{"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write"]}],  # Contributor
        [{"actions": ["microsoft.apimanagement/SERVICE/*"], "notActions": []}],  # case-insensitive
        [  # union over entries
            {"actions": ["Microsoft.ApiManagement/service/write"], "notActions": []},
            {"actions": ["Microsoft.ApiManagement/service/*/write"], "notActions": []},
            {"actions": ["Microsoft.ApiManagement/service/*/delete"], "notActions": []},
        ],
    ],
)
def test_preflight_passes_when_every_write_is_granted(entries: list[dict[str, Any]]) -> None:
    result = evaluate_permissions(entries, now=T0)
    assert result.passed
    assert result.missing == []
    assert result.required == list(REQUIRED_WRITE_ACTIONS)
    assert result.checked_at == T0


def test_preflight_fails_for_a_reader() -> None:
    result = evaluate_permissions([{"actions": ["*/read"], "notActions": []}], now=T0)
    assert not result.passed
    assert result.missing == list(REQUIRED_WRITE_ACTIONS)


def test_not_actions_deny_write_within_their_entry_only() -> None:
    denied = [
        {
            "actions": ["Microsoft.ApiManagement/service/*"],
            "notActions": ["Microsoft.ApiManagement/service/subscriptions/*"],
        }
    ]
    result = evaluate_permissions(denied, now=T0)
    assert not result.passed
    assert result.missing == [
        "Microsoft.ApiManagement/service/subscriptions/write",
        "Microsoft.ApiManagement/service/subscriptions/delete",
    ]
    # Another entry granting it restores the permission (Azure RBAC union semantics).
    regranted = [*denied, {"actions": ["Microsoft.ApiManagement/service/subscriptions/*"]}]
    assert evaluate_permissions(regranted, now=T0).passed


def test_preflight_ignores_malformed_entries() -> None:
    result = evaluate_permissions([{"actions": "not-a-list"}, {"notActions": [3]}], now=T0)
    assert not result.passed


def test_preflight_model_is_consistent() -> None:
    with pytest.raises(ValidationError):
        ModePreflight(passed=True, checked_at=T0, required=["a"], missing=["a"])
    with pytest.raises(ValidationError):
        ModePreflight(passed=False, checked_at=T0, required=["a"], missing=[])


# -- registration invariant ---------------------------------------------------------------------


def test_new_registration_is_observe_and_manage_needs_the_switch() -> None:
    registration = _registration()
    assert registration.mode == "observe"
    assert registration.mode_revision == 0
    assert registration.preflight is None
    data = registration.model_dump()
    with pytest.raises(ValidationError):
        GatewayRegistration.model_validate({**data, "mode": "manage"})
    failed = evaluate_permissions([], now=T0)
    with pytest.raises(ValidationError):
        GatewayRegistration.model_validate(
            {
                **data,
                "mode": "manage",
                "preflight": failed,
                "mode_changed_by": PSEUDONYM,
                "mode_changed_at": T0,
                "mode_revision": 1,
            }
        )
    ok = GatewayRegistration.model_validate(
        {
            **data,
            "mode": "manage",
            "preflight": _passed(),
            "mode_changed_by": PSEUDONYM,
            "mode_changed_at": T0,
            "mode_revision": 1,
        }
    )
    assert ok.mode == "manage"


# -- intent shape ---------------------------------------------------------------------------------


def test_mode_target_and_version_name_the_gateway_and_revision() -> None:
    registration = _registration()
    target = mode_target(registration)
    assert target == {
        "canonical_id": f"commercial:contoso:apim:{MODE_TARGET_TYPE}:{registration.id}",
        "entity_type": "apim_gateway_mode",
    }
    assert gateway_id_of_target(target["canonical_id"]) == registration.id
    assert mode_target_version(registration) == "mode-r0-observe"
    with pytest.raises(InvalidSchemaError):
        gateway_id_of_target("commercial:contoso:apim:apim_gateway_mode:not-a-gateway")


def test_mode_change_diff_round_trips() -> None:
    diff = mode_change_diff("manage", PSEUDONYM)
    assert parse_mode_change(diff) == ModeChange(desired="manage", changed_by=PSEUDONYM)
    assert parse_mode_change(list(reversed(diff))).desired == "manage"


@pytest.mark.parametrize(
    "operations",
    [
        [],
        [{"op": "replace", "path": "/mode", "value": "manage"}],
        [
            {"op": "replace", "path": "/mode", "value": "admin"},
            {"op": "replace", "path": "/mode_changed_by", "value": PSEUDONYM},
        ],
        [
            {"op": "add", "path": "/mode", "value": "manage"},
            {"op": "replace", "path": "/mode_changed_by", "value": PSEUDONYM},
        ],
        [
            {"op": "replace", "path": "/mode", "value": "manage"},
            {"op": "replace", "path": "/mode", "value": "observe"},
        ],
        [
            {"op": "replace", "path": "/mode", "value": "manage"},
            {"op": "replace", "path": "/mode_changed_by", "value": PSEUDONYM},
            {"op": "replace", "path": "/tier", "value": "premium"},
        ],
    ],
)
def test_parse_mode_change_rejects_anything_else(operations: list[dict[str, Any]]) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        parse_mode_change(operations)
    assert info.value.reason == "bad_mode_change"


# -- refusals -------------------------------------------------------------------------------------


def test_government_manage_is_disabled_with_a_reason() -> None:
    assert manage_refusal("commercial") is None
    refusal = manage_refusal("government")
    assert isinstance(refusal, CapabilityUnavailableError)
    assert refusal.reason == GATEWAY_MANAGE_UNAVAILABLE
    assert refusal.detail


async def test_switch_to_manage_needs_a_passed_preflight_and_bumps_the_revision() -> None:
    switch, store, saved, activity = await _switch()
    change = ModeChange(desired="manage", changed_by=PSEUDONYM)
    updated = await switch.switch(mode_target_version(saved), change, _passed())
    assert updated.mode == "manage"
    assert updated.mode_revision == 1
    assert updated.mode_changed_by == PSEUDONYM
    assert updated.mode_changed_at == T0 + timedelta(minutes=5)
    assert updated.preflight is not None and updated.preflight.passed
    assert updated.etag != saved.etag
    assert activity.asked == [saved.id]
    stored = await store.get(CUSTOMER, DOMAIN, saved.id)
    assert stored is not None and stored.mode == "manage"
    assert mode_target_version(stored) == "mode-r1-manage"


async def test_failed_preflight_refuses_and_changes_nothing() -> None:
    switch, store, saved, _ = await _switch()
    denied = evaluate_permissions([{"actions": ["*/read"]}], now=T0)
    with pytest.raises(CapabilityUnavailableError) as info:
        await switch.switch(mode_target_version(saved), ModeChange("manage", PSEUDONYM), denied)
    assert info.value.reason == GATEWAY_PREFLIGHT_FAILED
    assert "Microsoft.ApiManagement/service/write" in (info.value.detail or "")
    with pytest.raises(CapabilityUnavailableError):
        await switch.switch(mode_target_version(saved), ModeChange("manage", PSEUDONYM), None)
    stored = await store.get(CUSTOMER, DOMAIN, saved.id)
    assert stored == saved


async def test_switch_is_refused_while_the_gateway_is_applying() -> None:
    switch, store, saved, _ = await _switch(busy=True)
    with pytest.raises(CapabilityUnavailableError) as info:
        await switch.switch(mode_target_version(saved), ModeChange("manage", PSEUDONYM), _passed())
    assert info.value.reason == GATEWAY_APPLYING
    assert await store.get(CUSTOMER, DOMAIN, saved.id) == saved


async def test_government_switch_to_manage_is_refused() -> None:
    switch, _, saved, _ = await _switch(cloud="government")
    with pytest.raises(CapabilityUnavailableError) as info:
        await switch.check(mode_target_version(saved), ModeChange("manage", PSEUDONYM))
    assert info.value.reason == GATEWAY_MANAGE_UNAVAILABLE


async def test_stale_and_unchanged_mode_are_refused() -> None:
    switch, _, saved, _ = await _switch()
    with pytest.raises(StaleVersionError) as stale:
        await switch.check("mode-r7-observe", ModeChange("manage", PSEUDONYM))
    assert stale.value.reason == "target_version_changed"
    with pytest.raises(InvalidSchemaError) as same:
        await switch.check(mode_target_version(saved), ModeChange("observe", PSEUDONYM))
    assert same.value.reason == MODE_UNCHANGED


async def test_switching_back_to_observe_needs_no_preflight_and_keeps_the_last_one() -> None:
    switch, _, saved, _ = await _switch()
    managed = await switch.switch(
        mode_target_version(saved), ModeChange("manage", PSEUDONYM), _passed()
    )
    back = await switch.switch(
        mode_target_version(managed), ModeChange("observe", "pn-other"), None
    )
    assert back.mode == "observe"
    assert back.mode_revision == 2
    assert back.mode_changed_by == "pn-other"
    assert back.preflight == managed.preflight


async def test_restore_puts_the_prior_mode_back_only_at_the_same_revision() -> None:
    switch, _, saved, _ = await _switch()
    managed = await switch.switch(
        mode_target_version(saved), ModeChange("manage", PSEUDONYM), _passed()
    )
    restored = await switch.restore(
        "observe", revision=managed.mode_revision, changed_by=PSEUDONYM, preflight=None
    )
    assert restored is not None and restored.mode == "observe"
    # A later switch moved on: nothing is restored over it.
    assert (
        await switch.restore("manage", revision=1, changed_by=PSEUDONYM, preflight=_passed())
        is None
    )
    with pytest.raises(CapabilityUnavailableError):
        await switch.restore("manage", revision=2, changed_by=PSEUDONYM, preflight=None)


# -- the observe-mode guard -----------------------------------------------------------------------


async def test_require_manage_refuses_observe_and_unknown_gateways() -> None:
    switch, store, saved, _ = await _switch()
    assert isinstance(store, GatewayModeLookup)
    with pytest.raises(CapabilityUnavailableError) as observe:
        await require_manage(store, CUSTOMER, saved.id)
    assert observe.value.reason == GATEWAY_OBSERVE_MODE
    with pytest.raises(CapabilityUnavailableError) as unknown:
        await require_manage(store, CUSTOMER, "gw-" + "f" * 32)
    assert unknown.value.reason == GATEWAY_NOT_REGISTERED
    with pytest.raises(CapabilityUnavailableError):
        await require_manage(store, "fabrikam", saved.id)  # another customer never matches
    with pytest.raises(CapabilityUnavailableError) as via_switch:
        await switch.require_manage()
    assert via_switch.value.reason == GATEWAY_OBSERVE_MODE
    await switch.switch(mode_target_version(saved), ModeChange("manage", PSEUDONYM), _passed())
    found = await require_manage(store, CUSTOMER, saved.id)
    assert found.mode == "manage"
    assert (await switch.require_manage()).mode == "manage"


async def test_a_reused_gateway_stays_observe_across_syncs() -> None:
    """Registration and sync never touch the mode; only the switch moves it."""
    _, store, saved, _ = await _switch()
    synced = await store.replace(
        saved.model_copy(update={"last_sync_status": "ok", "tier": "premium_v2"}),
        if_match=saved.etag or "",
    )
    assert synced.mode == "observe"
    assert synced.mode_revision == 0
    with pytest.raises(CapabilityUnavailableError):
        await require_manage(store, CUSTOMER, saved.id)
