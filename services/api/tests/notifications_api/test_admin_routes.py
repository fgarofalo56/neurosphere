"""PRP-107 item 7: notification channel, subscription and delivery admin routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from authz.authz_helpers import CUSTOMER, FakeClock, make_validator  # pyright: ignore[reportMissingImports]
from neurosphere_api.notifications.service import AdminHooks, NotificationsAdmin
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_contracts.notifications.v1.notification import NotificationDelivery
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.notifications.models import NotificationChannel
from neurosphere_core.notifications.senders import verify_signature
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]

from .admin_harness import (
    ANALYST,
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN,
    DOMAIN_ADMIN,
    SIGNING_SECRET,
    Receiver,
    World,
    channel_body,
    configure_env,
    seeded_policies,
    subscription_body,
)

HOST = "hooks.example.org"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> World:
    built = World.build()
    asyncio.run(built.configure(HOST, "localhost"))
    return built


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    sink = Receiver()
    yield sink
    sink.close()


def _create(world: World, body: dict[str, Any] | None = None) -> Any:
    return world.client().post(
        f"{BASE}/channels", json=body or channel_body(), headers=world.auth(CUSTOMER_ADMIN)
    )


def _problem(response: Any) -> tuple[int, str, str | None]:
    body = response.json()
    return response.status_code, body["code"], body.get("reason")


def _delivery(
    n: int, channel_id: str, status: str, *, error: str | None = None, minute: int = 0
) -> NotificationDelivery:
    return NotificationDelivery.model_validate(
        {
            "schema_version": "1.0.0",
            "notification_id": f"00000000-0000-4000-8000-{n:012d}",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": DOMAIN,
            "channel_id": channel_id,
            "subscription_id": "ops-sub",
            "event_class": "hitl_item_assigned",
            "severity": "medium",
            "subject": {
                "canonical_id": "commercial:contoso:catalog:review_item:item-1",
                "entity_type": "review_item",
            },
            "title": f"Review item {n} assigned",
            "link": f"/review/item-{n}",
            "correlation_id": "corr-1",
            "dedup_key": "sha256:" + hashlib.sha256(str(n).encode()).hexdigest(),
            "status": status,
            "attempts": 1,
            "last_error_code": error,
            "created_at": f"2026-11-26T09:{minute:02d}:00Z",
        }
        | ({} if error else {"last_error_code": None})
    )


def test_channel_kinds_report_the_registry_status(world: World) -> None:
    response = world.client().get(f"{BASE}/channel-kinds", headers=world.auth(CUSTOMER_ADMIN))
    assert response.status_code == 200
    kinds = {i["kind"]: (i["status"], i["reason"]) for i in response.json()["items"]}
    assert kinds["webhook"] == ("buildable", None)
    assert kinds["teams_webhook"][0] == "degraded"
    assert kinds["email"] == ("not_built", "email_transport_not_built")


def test_channel_crud_with_etag_and_if_match(world: World) -> None:
    created = _create(world)
    assert created.status_code == 201, created.text
    view = created.json()
    assert created.headers["etag"] == view["etag"] and view["etag"].startswith('"')
    assert view["version"] == 1
    assert view["delivery_counts"] == {
        "pending": 0,
        "sending": 0,
        "delivered": 0,
        "failed": 0,
        "dead_lettered": 0,
        "suppressed": 0,
    }
    assert view["last_error_code"] is None
    client, headers = world.client(), world.auth(CUSTOMER_ADMIN)
    got = client.get(f"{BASE}/channels/ops-hook", headers=headers)
    assert got.status_code == 200 and got.headers["etag"] == view["etag"]
    assert [
        i["channel"]["channel_id"]
        for i in client.get(f"{BASE}/channels", headers=headers).json()["items"]
    ] == ["ops-hook"]

    changed = channel_body(display_name="Renamed", enabled=False)
    missing = client.put(f"{BASE}/channels/ops-hook", json=changed, headers=headers)
    assert _problem(missing)[:1] == (422,) and _problem(missing)[2] == "precondition_required"
    stale = client.put(
        f"{BASE}/channels/ops-hook", json=changed, headers={**headers, "If-Match": '"nope"'}
    )
    assert _problem(stale)[:2] == (409, "stale_version")
    updated = client.put(
        f"{BASE}/channels/ops-hook", json=changed, headers={**headers, "If-Match": view["etag"]}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2 and updated.json()["etag"] != view["etag"]
    assert updated.headers["etag"] == updated.json()["etag"]
    assert updated.json()["channel"]["enabled"] is False

    refused = client.delete(f"{BASE}/channels/ops-hook", headers=headers)
    assert _problem(refused)[2] == "precondition_required"
    deleted = client.delete(
        f"{BASE}/channels/ops-hook", headers={**headers, "If-Match": updated.json()["etag"]}
    )
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(f"{BASE}/channels/ops-hook", headers=headers).status_code == 404
    assert client.get(f"{BASE}/channels", headers=headers).json()["items"] == []


def test_path_and_body_ids_must_agree(world: World) -> None:
    etag = _create(world).json()["etag"]
    response = world.client().put(
        f"{BASE}/channels/ops-hook",
        json=channel_body("other"),
        headers={**world.auth(CUSTOMER_ADMIN), "If-Match": etag},
    )
    assert _problem(response) == (422, "invalid_schema", "path_body_mismatch")


def test_email_channel_is_refused_as_not_built(world: World) -> None:
    response = _create(world, channel_body(kind="email", hmac_credential=None))
    assert _problem(response) == (409, "capability_unavailable", "channel_kind_not_built")


def test_host_off_the_allow_list_is_refused_with_its_reason(world: World) -> None:
    response = _create(world, channel_body(allowed_host="blocked.example.net"))
    assert _problem(response) == (422, "invalid_schema", "host_not_allowed")


def test_missing_notifications_setting_is_a_conflict() -> None:
    bare = World.build()
    response = _create(bare)
    assert _problem(response) == (409, "capability_unavailable", "notifications_not_configured")


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"local_sink": True, "local_sink_url": None}, "local_sink_url_required"),
        ({"local_sink_url": "http://127.0.0.1:9/h"}, "local_sink_url_not_allowed"),
        ({"endpoint_credential": None}, "endpoint_credential_required"),
        ({"hmac_credential": None}, "hmac_credential_required"),
        ({"cloud": "government"}, "cloud_boundary"),
        (
            {
                "endpoint_credential": {
                    "kind": "key_vault_secret",
                    "secret_uri": "https://ns-kv.vault.usgovcloudapi.net/secrets/ops",
                }
            },
            "cloud_boundary",
        ),
        ({"customer_id": "fabrikam"}, "cross_customer"),
    ],
)
def test_contract_rules_and_boundaries_are_enforced(
    world: World, over: dict[str, Any], reason: str
) -> None:
    response = _create(world, channel_body(**over))
    assert _problem(response) == (422, "invalid_schema", reason), response.text


def test_local_sink_is_refused_outside_local_env(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_state = world.composed.app.state
    admin_state.settings = admin_state.settings.model_copy(update={"env": "production"})
    body = channel_body(
        local_sink=True,
        local_sink_url="http://127.0.0.1:9/hook",
        endpoint_credential=None,
        allowed_host="localhost",
    )
    assert _problem(_create(world, body)) == (422, "invalid_schema", "local_sink_not_permitted")


def _government_admin(world: World) -> NotificationsAdmin:
    plane = world.composed.app.state.notifications
    scope = SimpleNamespace(customer_id=CUSTOMER)
    return NotificationsAdmin(
        plane,
        scope,  # type: ignore[arg-type]
        audit=None,
        cloud="government",
        ns_env="production",
        hooks=AdminHooks(),
    )


def test_government_deployment_refuses_a_commercial_channel_and_an_off_list_host(
    world: World,
) -> None:
    admin = _government_admin(world)
    commercial = NotificationChannel.model_validate(channel_body())
    with pytest.raises(InvalidSchemaError) as boundary:
        asyncio.run(admin._check_channel(commercial))  # pyright: ignore[reportPrivateUsage]
    assert boundary.value.reason == "cloud_boundary"
    gov_vault = "https://ns-kv.vault.usgovcloudapi.net/secrets/"
    government = NotificationChannel.model_validate(
        channel_body(
            cloud="government",
            domain_id="government:contoso:neurosphere:domain:finance",
            endpoint_credential={"kind": "key_vault_secret", "secret_uri": gov_vault + "e"},
            hmac_credential={"kind": "key_vault_secret", "secret_uri": gov_vault + "h"},
        )
    )
    asyncio.run(admin._check_channel(government))  # pyright: ignore[reportPrivateUsage]
    stray = government.model_copy(update={"allowed_host": "stray.example.net"})
    with pytest.raises(InvalidSchemaError) as off_list:
        asyncio.run(admin._check_channel(stray))  # pyright: ignore[reportPrivateUsage]
    assert off_list.value.reason == "host_not_allowed"


def test_test_send_reaches_a_real_local_receiver_signed(
    world: World, receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    body = channel_body(
        "local-hook",
        local_sink=True,
        local_sink_url=receiver.url,
        endpoint_credential=None,
        allowed_host="localhost",
    )
    created = _create(world, body)
    assert created.status_code == 201, created.text
    response = world.client().post(
        f"{BASE}/channels/local-hook/test", headers=world.auth(CUSTOMER_ADMIN)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "status_code": 200, "reason_code": None}
    (sent,) = receiver.requests
    payload = json.loads(sent["body"])
    assert payload["title"] == "NeuroSphere test notification"
    assert verify_signature(
        SIGNING_SECRET,
        sent["headers"]["x-neurosphere-timestamp"],
        sent["body"],
        sent["headers"]["x-neurosphere-signature"],
    )
    operations = [r.get("operation") for r in world.records()]
    assert operations.count("notification.channel.test") == 2  # before and after
    everything = json.dumps(world.records()) + caplog.text + response.text + created.text
    assert SIGNING_SECRET not in everything
    assert receiver.url not in json.dumps(world.records()) + caplog.text


def test_failed_test_send_reports_the_reason_not_an_error(world: World) -> None:
    sink = Receiver(status=500)
    try:
        body = channel_body(
            "flaky-hook",
            local_sink=True,
            local_sink_url=sink.url,
            endpoint_credential=None,
            allowed_host="localhost",
        )
        assert _create(world, body).status_code == 201
        response = world.client().post(
            f"{BASE}/channels/flaky-hook/test", headers=world.auth(CUSTOMER_ADMIN)
        )
    finally:
        sink.close()
    result = response.json()
    assert response.status_code == 200 and result["ok"] is False
    assert result["status_code"] == 500 and result["reason_code"]
    after = [r for r in world.records() if r.get("operation") == "notification.channel.test"][-1]
    assert "failed" in json.dumps(after)


def test_writes_are_audited_without_references_or_secrets(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    created = _create(world)
    client, headers = world.client(), world.auth(CUSTOMER_ADMIN)
    sub = client.post(f"{BASE}/subscriptions", json=subscription_body(), headers=headers)
    assert sub.status_code == 201, sub.text
    client.delete(
        f"{BASE}/subscriptions/ops-sub", headers={**headers, "If-Match": sub.json()["etag"]}
    )
    client.delete(
        f"{BASE}/channels/ops-hook", headers={**headers, "If-Match": created.json()["etag"]}
    )
    records = world.records()
    text = json.dumps(records)
    for operation in (
        "notification.channel.create",
        "notification.channel.delete",
        "notification.subscription.create",
        "notification.subscription.delete",
    ):
        assert text.count(operation) == 2, operation
    assert all(r["chain_id"] == f"{CUSTOMER}.admin-config" for r in records)
    assert "ns-kv" not in text and "vault.azure.net" not in text
    assert "vault.azure.net" not in caplog.text and SIGNING_SECRET not in caplog.text


def test_subscription_crud_and_channel_checks(world: World) -> None:
    client, headers = world.client(), world.auth(CUSTOMER_ADMIN)
    unknown = client.post(f"{BASE}/subscriptions", json=subscription_body(), headers=headers)
    assert _problem(unknown) == (422, "invalid_schema", "unknown_channel")
    _create(world)
    created = client.post(f"{BASE}/subscriptions", json=subscription_body(), headers=headers)
    assert created.status_code == 201
    view = created.json()
    assert created.headers["etag"] == view["etag"] and view["version"] == 1
    cross = client.post(
        f"{BASE}/subscriptions",
        json=subscription_body("sub-gov", cloud="government"),
        headers=headers,
    )
    assert _problem(cross)[2] == "cloud_boundary"
    got = client.get(f"{BASE}/subscriptions/ops-sub", headers=headers)
    assert got.status_code == 200 and got.headers["etag"] == view["etag"]
    assert len(client.get(f"{BASE}/subscriptions", headers=headers).json()["items"]) == 1
    changed = subscription_body(min_severity="high", enabled=False)
    no_match = client.put(f"{BASE}/subscriptions/ops-sub", json=changed, headers=headers)
    assert _problem(no_match)[2] == "precondition_required"
    updated = client.put(
        f"{BASE}/subscriptions/ops-sub",
        json=changed,
        headers={**headers, "If-Match": view["etag"]},
    )
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert updated.json()["subscription"]["enabled"] is False
    stale = client.delete(
        f"{BASE}/subscriptions/ops-sub", headers={**headers, "If-Match": view["etag"]}
    )
    assert _problem(stale)[:2] == (409, "stale_version")
    gone = client.delete(
        f"{BASE}/subscriptions/ops-sub", headers={**headers, "If-Match": updated.json()["etag"]}
    )
    assert gone.status_code == 204 and gone.content == b""
    assert client.get(f"{BASE}/subscriptions", headers=headers).json()["items"] == []


def test_deliveries_filter_counts_and_last_error(world: World) -> None:
    _create(world)
    _create(world, channel_body("second-hook"))
    rows = [
        _delivery(1, "ops-hook", "delivered", minute=1),
        _delivery(2, "ops-hook", "failed", error="http_500", minute=2),
        _delivery(3, "ops-hook", "pending", minute=3),
        _delivery(4, "second-hook", "pending", minute=4),
    ]
    for row in rows:
        asyncio.run(world.outbox.create_if_absent(row))
    client, headers = world.client(), world.auth(CUSTOMER_ADMIN)
    everything = client.get(f"{BASE}/deliveries", headers=headers).json()["items"]
    assert [d["status"] for d in everything] == ["pending", "pending", "failed", "delivered"]
    failed = client.get(f"{BASE}/deliveries", params={"status": "failed"}, headers=headers)
    assert [d["notification_id"][-1] for d in failed.json()["items"]] == ["2"]
    mine = client.get(f"{BASE}/deliveries", params={"channel_id": "second-hook"}, headers=headers)
    assert [d["channel_id"] for d in mine.json()["items"]] == ["second-hook"]
    one = client.get(f"{BASE}/deliveries", params={"limit": 1}, headers=headers)
    assert len(one.json()["items"]) == 1
    bad = client.get(f"{BASE}/deliveries", params={"status": "bogus"}, headers=headers)
    assert bad.status_code == 422
    view = client.get(f"{BASE}/channels/ops-hook", headers=headers).json()
    assert view["delivery_counts"]["delivered"] == 1
    assert view["delivery_counts"]["failed"] == 1 and view["delivery_counts"]["pending"] == 1
    assert view["last_error_code"] == "http_500"
    assert (
        client.get(f"{BASE}/channels/second-hook", headers=headers).json()["last_error_code"]
        is None
    )


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST])
def test_callers_without_customer_level_config_manage_get_403_and_a_denial(
    world: World, who: str
) -> None:
    etag = _create(world).json()["etag"]
    client = world.client()
    headers = {**world.auth(who), "If-Match": etag}
    calls = [
        client.get(f"{BASE}/channel-kinds", headers=headers),
        client.get(f"{BASE}/channels", headers=headers),
        client.post(f"{BASE}/channels", json=channel_body("x"), headers=headers),
        client.get(f"{BASE}/channels/ops-hook", headers=headers),
        client.put(f"{BASE}/channels/ops-hook", json=channel_body(), headers=headers),
        client.delete(f"{BASE}/channels/ops-hook", headers=headers),
        client.post(f"{BASE}/channels/ops-hook/test", headers=headers),
        client.get(f"{BASE}/subscriptions", headers=headers),
        client.post(f"{BASE}/subscriptions", json=subscription_body(), headers=headers),
        client.get(f"{BASE}/subscriptions/ops-sub", headers=headers),
        client.put(f"{BASE}/subscriptions/ops-sub", json=subscription_body(), headers=headers),
        client.delete(f"{BASE}/subscriptions/ops-sub", headers=headers),
        client.get(f"{BASE}/deliveries", headers=headers),
    ]
    assert [c.status_code for c in calls] == [403] * len(calls)
    assert len(world.denials.attempts) >= len(calls)
    assert {a.path.split("/api/v1/admin/notifications")[0] for a in world.denials.attempts} == {""}
    stored = client.get(f"{BASE}/channels/ops-hook", headers=world.auth(CUSTOMER_ADMIN))
    assert stored.json()["version"] == 1


def test_no_token_is_401(world: World) -> None:
    assert world.client().get(f"{BASE}/channels").status_code == 401


def test_routes_answer_503_when_the_plane_is_not_built() -> None:
    clock = FakeClock()

    def data(ctx: BuildContext) -> None:
        ctx.ok("audit")

    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=seeded_policies(),
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
    )
    composed = compose(
        overrides,
        builders=(authz_builder.BUILDER, BuilderSpec("stub-data", ("audit",), data)),
        clock=clock,
    )
    response = composed.client().get(f"{BASE}/channels", headers=composed.auth(CUSTOMER_ADMIN))
    assert _problem(response) == (503, "dependency_transient", "capability_unavailable")


def test_a_malformed_body_is_a_422_that_echoes_no_value(world: World) -> None:
    sentinel = "SENTINEL-NOT-A-REAL-VALUE"
    body = channel_body(
        kind="smoke-signal", endpoint_credential={"kind": "nope", "secret_uri": sentinel}
    )
    response = _create(world, body)
    assert _problem(response)[:2] == (422, "invalid_schema")
    assert sentinel not in response.text
