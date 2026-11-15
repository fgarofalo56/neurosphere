"""PRP-41 item 3: producer admin routes, round trip, authorization and ingest effect."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.ingest.auth import ProducerRegistration, StaticProducerRegistry, hash_secret
from producer_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    EVENTS,
    ProducerWorld,
    configure_env,
    telemetry_event,
)

CE = {"content-type": "application/cloudevents+json"}
CREATE: dict[str, Any] = {
    "producer_id": "poller-1",
    "cloud": "commercial",
    "sources": {"src-app": "application"},
}


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> ProducerWorld:
    return ProducerWorld.build()


def client(world: ProducerWorld) -> TestClient:
    return world.composed.client()


def post_event(c: TestClient, producer: str, secret: str) -> int:
    return c.post(
        EVENTS,
        content=json.dumps(telemetry_event("src-app")),
        headers={**CE, "Authorization": f"Bearer {producer}.{secret}"},
    ).status_code


def test_component_is_ok(world: ProducerWorld) -> None:
    assert world.composed.registry.get("admin_producers").state == "ok"


def test_create_then_authenticate_immediately(world: ProducerWorld) -> None:
    c = client(world)
    response = c.post(BASE, json=CREATE, headers=world.auth(CUSTOMER_ADMIN))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["shown_once"] is True and body["producer_id"] == "poller-1"
    assert response.headers["etag"] and response.headers["cache-control"] == "no-store"
    assert post_event(c, "poller-1", body["secret"]) == 202
    assert post_event(c, "poller-1", "wrong-secret-value") == 401


def test_round_trip_rotate_disable_enable(world: ProducerWorld) -> None:
    c = client(world)
    h = world.auth(CUSTOMER_ADMIN)
    created = c.post(BASE, json=CREATE, headers=h)
    old = created.json()["secret"]
    etag = created.headers["etag"]
    rotated = c.post(f"{BASE}/poller-1/rotate", headers={**h, "If-Match": etag})
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()["secret"]
    assert new != old
    assert post_event(c, "poller-1", old) == 401  # immediately on this replica
    assert post_event(c, "poller-1", new) == 202
    etag = rotated.headers["etag"]
    disabled = c.post(f"{BASE}/poller-1/disable", headers={**h, "If-Match": etag})
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    assert post_event(c, "poller-1", new) == 401
    unknown = c.post(
        EVENTS,
        content=json.dumps(telemetry_event("src-app")),
        headers={**CE, "Authorization": "Bearer ghost.whatever"},
    )
    off = c.post(
        EVENTS,
        content=json.dumps(telemetry_event("src-app")),
        headers={**CE, "Authorization": f"Bearer poller-1.{new}"},
    )
    same = {k: v for k, v in off.json().items() if k != "correlation_id"}
    assert same == {k: v for k, v in unknown.json().items() if k != "correlation_id"}
    enabled = c.post(f"{BASE}/poller-1/enable", headers={**h, "If-Match": disabled.headers["etag"]})
    assert enabled.status_code == 200 and enabled.json()["status"] == "active"
    assert post_event(c, "poller-1", new) == 202  # restored with the current secret


def test_missing_and_stale_if_match(world: ProducerWorld) -> None:
    c = client(world)
    h = world.auth(CUSTOMER_ADMIN)
    created = c.post(BASE, json=CREATE, headers=h)
    missing = c.post(f"{BASE}/poller-1/rotate", headers=h)
    assert missing.status_code == 422
    assert "precondition_required" in missing.text
    ok = c.post(f"{BASE}/poller-1/disable", headers={**h, "If-Match": created.headers["etag"]})
    assert ok.status_code == 200
    stale = c.post(f"{BASE}/poller-1/enable", headers={**h, "If-Match": created.headers["etag"]})
    assert stale.status_code == 409


def test_reads_never_carry_secret_or_digest(world: ProducerWorld) -> None:
    c = client(world)
    h = world.auth(CUSTOMER_ADMIN)
    created = c.post(BASE, json=CREATE, headers=h).json()
    one = c.get(f"{BASE}/poller-1", headers=h)
    page = c.get(BASE, headers=h)
    assert one.status_code == 200 and one.headers["etag"]
    for text in (one.text, page.text):
        assert created["secret"] not in text and created["secret_sha256"] not in text
        assert "secret" not in text
    assert page.json()["items"][0]["producer_id"] == "poller-1"
    stored = world.repository._docs  # pyright: ignore[reportPrivateUsage]
    dumped = json.dumps([d.model_dump(mode="json") for d in stored.values()])
    assert created["secret"] not in dumped and created["secret_sha256"] in dumped


def test_duplicate_and_cross_scope_refused_without_write(world: ProducerWorld) -> None:
    c = client(world)
    h = world.auth(CUSTOMER_ADMIN)
    assert c.post(BASE, json=CREATE, headers=h).status_code == 201
    assert c.post(BASE, json=CREATE, headers=h).status_code == 409
    gov = c.post(BASE, json={**CREATE, "producer_id": "gov", "cloud": "government"}, headers=h)
    assert gov.status_code == 422
    other = c.post(
        BASE, json={**CREATE, "producer_id": "other", "customer_id": "fabrikam"}, headers=h
    )
    assert other.status_code == 403
    ids = [d.id.root for d in world.repository._docs.values()]  # pyright: ignore[reportPrivateUsage]
    assert ids == ["poller-1"]


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST])
def test_non_customer_level_callers_get_403(world: ProducerWorld, who: str) -> None:
    c = client(world)
    h = world.auth(who)
    calls = [
        c.post(BASE, json=CREATE, headers=h),
        c.get(BASE, headers=h),
        c.get(f"{BASE}/poller-1", headers=h),
        c.post(f"{BASE}/poller-1/rotate", headers={**h, "If-Match": '"x"'}),
        c.post(f"{BASE}/poller-1/disable", headers={**h, "If-Match": '"x"'}),
        c.post(f"{BASE}/poller-1/enable", headers={**h, "If-Match": '"x"'}),
    ]
    assert [r.status_code for r in calls] == [403] * 6
    assert not world.repository._docs  # pyright: ignore[reportPrivateUsage]


def test_unauthenticated_is_401(world: ProducerWorld) -> None:
    assert client(world).get(BASE).status_code == 401


def test_file_producer_still_works_and_store_wins() -> None:
    file_secret = hash_secret("fixture-a")[:32]  # computed, not a literal
    fallback = StaticProducerRegistry(
        [
            ProducerRegistration(
                producer_id="poller-1",
                secret_sha256=hash_secret(file_secret),
                customer_id="contoso",
                cloud="commercial",
                sources={"src-app": "application"},
            )
        ]
    )
    world = ProducerWorld.build(fallback=fallback)
    c = client(world)
    assert post_event(c, "poller-1", file_secret) == 202
    created = c.post(BASE, json=CREATE, headers=world.auth(CUSTOMER_ADMIN)).json()
    assert post_event(c, "poller-1", file_secret) == 401
    assert post_event(c, "poller-1", created["secret"]) == 202


def test_audit_records_carry_no_secret_or_digest(world: ProducerWorld) -> None:
    c = client(world)
    h = world.auth(CUSTOMER_ADMIN)
    created = c.post(BASE, json=CREATE, headers=h)
    c.post(f"{BASE}/poller-1/rotate", headers={**h, "If-Match": created.headers["etag"]})
    c.post(f"{BASE}/poller-1/rotate", headers=h)  # refused: no If-Match
    text = json.dumps(world.records())
    secret = created.json()["secret"]
    assert secret not in text and created.json()["secret_sha256"] not in text
    ops = {r.get("operation") or r.get("context", {}).get("operation") for r in world.records()}
    assert "producer.create" in text and "producer.rotate" in text, ops
    assert "poller-1" in text
