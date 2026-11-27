"""ABAC negative suite for the notification admin routes (PRP-107 item 7).

The suite world serves the real application router table, so ``/api/v1/admin/notifications`` is
mounted; this module installs the notifications plane on each deployment and asserts that every
route refuses, per dimension, with a recorded denial and no write:

=================================  ==========================================================
Dimension                          Expected refusal
=================================  ==========================================================
no role (viewer, analyst, steward) 403 ``permission_missing``
security auditor                   403 (holds no ``config.manage``)
ordinary domain admin              403 ``customer_scope_required``
expired control-domain admin       403 ``permission_missing``
other customer                     401 / 404 (never another's config); body of another customer 422
other cloud                        422 ``cloud_boundary`` (nothing stored)
=================================  ==========================================================
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.notifications.router import HOOKS_ATTRIBUTE
from neurosphere_api.notifications.service import AdminHooks
from neurosphere_api.runtime.builders.notifications import NotificationsPlane
from neurosphere_core.actions.permissions import GrantTablePermissionRechecker
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.auth.scope import Role
from neurosphere_core.notifications import (
    ChannelRegistry,
    InMemoryOutboxStore,
    NotificationPublisher,
    Outbox,
    SubscriptionResolver,
)
from neurosphere_core.notifications.hitl import OutboxNotifier

from .test_admin_connectors import (  # pyright: ignore[reportPrivateUsage]
    CONTROL_ADMIN_OID,
    EXPIRED_CONTROL_OID,
    _bearer,
    _seed,
)
from .world import Deployment, Who, World, domain_id

BASE = "/api/v1/admin/notifications"
FIN = "finance"
ENDPOINT = "https://ns-kv.vault.azure.net/secrets/ops-endpoint"
SIGNING = "https://ns-kv.vault.azure.net/secrets/ops-signing"
GOV_ENDPOINT = "https://ns-kv.vault.usgovcloudapi.net/secrets/ops-endpoint"
ADMIN = Who("contoso", FIN, Role.ADMIN)
DENIED_ROLES = (Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.SECURITY_AUDITOR)
HOST = "hooks.example.org"


def channel(customer: str = "contoso", **over: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "channel_id": "ops-hook",
        "cloud": "commercial",
        "customer_id": customer,
        "domain_id": domain_id(customer, FIN),
        "display_name": "Ops hook",
        "kind": "webhook",
        "allowed_host": HOST,
        "endpoint_credential": {"kind": "key_vault_secret", "secret_uri": ENDPOINT},
        "hmac_credential": {"kind": "key_vault_secret", "secret_uri": SIGNING},
        "local_sink": False,
        "local_sink_url": None,
        "enabled": True,
    }
    result.update(over)
    return result


def subscription(customer: str = "contoso", **over: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "subscription_id": "ops-sub",
        "cloud": "commercial",
        "customer_id": customer,
        "domain_id": domain_id(customer, FIN),
        "channel_id": "ops-hook",
        "event_classes": ["hitl_item_assigned"],
        "audience_roles": ["domain_steward"],
        "min_severity": "medium",
        "enabled": True,
    }
    result.update(over)
    return result


@dataclass
class Plane:
    repository: InMemoryAdminConfigRepository


def _install(dep: Deployment) -> Plane:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    registry = ChannelRegistry(repository)
    store = InMemoryOutboxStore()
    outbox = Outbox(store)
    resolver = SubscriptionResolver(registry, GrantTablePermissionRechecker())
    publisher = NotificationPublisher(resolver, outbox, registry)
    dep.app.state.notifications = NotificationsPlane(
        registry=registry,
        store=store,
        outbox=outbox,
        resolver=resolver,
        publisher=publisher,
        notifier=OutboxNotifier(publisher),
    )
    setattr(dep.app.state, HOOKS_ATTRIBUTE, AdminHooks())
    return Plane(repository)


async def _configure(plane: Plane, customer: str) -> None:
    await plane.repository.create(
        customer,
        "system_setting",
        "notifications",
        {
            "schema_version": "1.0.0",
            "setting_key": "notifications",
            "enabled": True,
            "notifications": {"egress_allowed_hosts": [HOST]},
        },
        updated_by=_principal(customer),
    )


def _principal(customer: str) -> str:
    from .test_admin_identity import pid_of

    return pid_of(CONTROL_ADMIN_OID, customer)


@pytest.fixture
def nworld(world: World) -> tuple[World, dict[str, Plane]]:
    planes: dict[str, Plane] = {}
    for name, dep in world.deployments.items():
        plane = _install(dep)
        asyncio.run(_configure(plane, dep.customer))
        planes[name] = plane
        _seed(dep, CONTROL_ADMIN_OID, expires_in=7 * 24 * 3600)
        _seed(dep, EXPIRED_CONTROL_OID, expires_in=10)
    return world, planes


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: str
    json: Callable[[], dict[str, Any] | None]


ROUTES: tuple[Route, ...] = (
    Route("kinds", "GET", f"{BASE}/channel-kinds", lambda: None),
    Route("channel-list", "GET", f"{BASE}/channels", lambda: None),
    Route("channel-create", "POST", f"{BASE}/channels", channel),
    Route("channel-get", "GET", f"{BASE}/channels/ops-hook", lambda: None),
    Route("channel-replace", "PUT", f"{BASE}/channels/ops-hook", channel),
    Route("channel-delete", "DELETE", f"{BASE}/channels/ops-hook", lambda: None),
    Route("channel-test", "POST", f"{BASE}/channels/ops-hook/test", lambda: None),
    Route("subscription-list", "GET", f"{BASE}/subscriptions", lambda: None),
    Route("subscription-create", "POST", f"{BASE}/subscriptions", subscription),
    Route("subscription-get", "GET", f"{BASE}/subscriptions/ops-sub", lambda: None),
    Route("subscription-replace", "PUT", f"{BASE}/subscriptions/ops-sub", subscription),
    Route("subscription-delete", "DELETE", f"{BASE}/subscriptions/ops-sub", lambda: None),
    Route("deliveries", "GET", f"{BASE}/deliveries", lambda: None),
)


def _call(dep: Deployment, route: Route, headers: dict[str, str]) -> Any:
    return dep.client.request(
        route.method, route.path, headers={**headers, "If-Match": '"x"'}, json=route.json()
    )


def _stored(plane: Plane, customer: str = "contoso") -> list[Any]:
    async def read() -> list[Any]:
        out: list[Any] = []
        for kind in ("notification_channel", "notification_subscription"):
            out.extend(await plane.repository.list_by_kind(customer, kind, include_retired=True))
        return out

    return asyncio.run(read())


def _reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


# ------------------------------------------------------------------ dimensions


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_roles_without_config_manage_are_denied(
    nworld: tuple[World, dict[str, Plane]], route: Route, role: Role
) -> None:
    world, planes = nworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(Who("contoso", FIN, role)))
    assert response.status_code == 403, response.text
    assert _reasons(dep), "a denial record is written"
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_ordinary_domain_admin_needs_customer_scope(
    nworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = nworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert "customer_scope_required" in _reasons(dep)
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_control_domain_admin_is_denied(
    nworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = nworld
    dep = world["contoso"]
    world.clock.advance(11)
    response = _call(dep, route, _bearer(dep, EXPIRED_CONTROL_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in _reasons(dep)
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_token_is_401(nworld: tuple[World, dict[str, Plane]], route: Route) -> None:
    world, _ = nworld
    assert _call(world["contoso"], route, {}).status_code == 401


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_other_customer_token_is_not_accepted(
    nworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = nworld
    contoso, fabrikam = world["contoso"], world["fabrikam"]
    assert _call(fabrikam, route, _bearer(contoso, CONTROL_ADMIN_OID)).status_code == 401
    assert _stored(planes["fabrikam"], "fabrikam") == []


def test_other_customer_cannot_see_or_name_anothers_config(
    nworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = nworld
    contoso, fabrikam = world["contoso"], world["fabrikam"]
    created = contoso.client.post(
        f"{BASE}/channels", headers=_bearer(contoso, CONTROL_ADMIN_OID), json=channel()
    )
    assert created.status_code == 201, created.text
    headers = _bearer(fabrikam, CONTROL_ADMIN_OID)
    assert fabrikam.client.get(f"{BASE}/channels/ops-hook", headers=headers).status_code == 404
    assert fabrikam.client.get(f"{BASE}/channels", headers=headers).json()["items"] == []
    cross = fabrikam.client.post(f"{BASE}/channels", headers=headers, json=channel("contoso"))
    assert cross.status_code == 422, cross.text
    assert cross.json()["reason"] == "cross_customer"
    assert _stored(planes["fabrikam"], "fabrikam") == []


def test_other_cloud_channel_credentials_and_subscriptions_are_refused(
    nworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = nworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    government_vault = channel(
        endpoint_credential={"kind": "key_vault_secret", "secret_uri": GOV_ENDPOINT}
    )
    government_cloud = channel(cloud="government")
    for payload in (government_vault, government_cloud):
        response = dep.client.post(f"{BASE}/channels", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["reason"] == "cloud_boundary"
    assert dep.client.post(f"{BASE}/channels", headers=headers, json=channel()).status_code == 201
    cross = dep.client.post(
        f"{BASE}/subscriptions", headers=headers, json=subscription(cloud="government")
    )
    assert cross.status_code == 422 and cross.json()["reason"] == "cloud_boundary"
    assert len(_stored(planes["contoso"])) == 1


def test_customer_level_admin_is_allowed(nworld: tuple[World, dict[str, Plane]]) -> None:
    world, planes = nworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    assert dep.client.post(f"{BASE}/channels", headers=headers, json=channel()).status_code == 201
    created = dep.client.post(f"{BASE}/subscriptions", headers=headers, json=subscription())
    assert created.status_code == 201, created.text
    assert len(_stored(planes["contoso"])) == 2
