"""PRP-44 item 2: domain and budget routes, audit, and the 403 matrix."""

from __future__ import annotations

import json
from typing import Any

import pytest
from platform_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    BASE,
    CONTROL,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    EXPIRED_ADMIN,
    FINANCE,
    PlatformWorld,
    budget_body,
    configure_env,
    domain_body,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> PlatformWorld:
    return PlatformWorld.build()


def _post(world: PlatformWorld, path: str, body: dict[str, Any], who: str = CUSTOMER_ADMIN) -> Any:
    return world.composed.client().post(f"{BASE}/{path}", json=body, headers=world.auth(who))


def _domain(world: PlatformWorld, body: dict[str, Any] | None = None) -> Any:
    return _post(world, "domains", body or domain_body())


def test_create_registers_the_domain_and_the_control_domain_with_an_etag(
    world: PlatformWorld,
) -> None:
    response = _domain(world)
    assert response.status_code == 201, response.text
    assert response.headers["etag"]
    assert response.json()["domain_id"] == FINANCE and response.json()["control_registered"]
    listed = world.composed.client().get(f"{BASE}/domains", headers=world.auth(CUSTOMER_ADMIN))
    ids = {d["domain_id"] for d in listed.json()["items"]}
    assert ids == {FINANCE, CONTROL}
    control = next(d for d in listed.json()["items"] if d["domain_id"] == CONTROL)
    assert control["is_control_domain"] is True


def test_duplicate_domain_is_409(world: PlatformWorld) -> None:
    assert _domain(world).status_code == 201
    again = _domain(world)
    assert again.status_code == 409


def test_domain_of_another_customer_or_cloud_is_422(world: PlatformWorld) -> None:
    for domain_id in (
        "commercial:fabrikam:neurosphere:domain:x",
        "government:contoso:neurosphere:domain:x",
    ):
        assert _domain(world, domain_body(domain_id)).status_code == 422


def test_control_domain_never_retires_and_a_retired_domain_keeps_its_record(
    world: PlatformWorld,
) -> None:
    etag = _domain(world).headers["etag"]
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    control = client.get(f"{BASE}/domains/{CONTROL}", headers=headers)
    refused = client.post(
        f"{BASE}/domains/{CONTROL}/retire", headers={**headers, "If-Match": control.headers["etag"]}
    )
    assert refused.status_code == 409
    missing_if_match = client.post(f"{BASE}/domains/{FINANCE}/retire", headers=headers)
    assert missing_if_match.status_code == 422
    retired = client.post(f"{BASE}/domains/{FINANCE}/retire", headers={**headers, "If-Match": etag})
    assert retired.status_code == 200 and retired.json()["status"] == "retired"
    assert client.get(f"{BASE}/domains/{FINANCE}", headers=headers).json()["status"] == "retired"
    active = client.get(f"{BASE}/domains", headers=headers).json()["items"]
    assert [d["domain_id"] for d in active] == [CONTROL]


def test_stale_if_match_on_retire_is_409(world: PlatformWorld) -> None:
    _domain(world)
    response = world.composed.client().post(
        f"{BASE}/domains/{FINANCE}/retire",
        headers={**world.auth(CUSTOMER_ADMIN), "If-Match": '"stale"'},
    )
    assert response.status_code == 409


def test_domain_writes_are_audited_without_bodies(world: PlatformWorld) -> None:
    _domain(world)
    records = world.records()
    assert len(records) == 2
    text = json.dumps(records)
    assert "domain.create" in text and "Finance" not in text
    assert all(r["chain_id"] == "contoso.admin-config" for r in records)


def test_budget_requires_a_registered_domain_and_sane_thresholds(world: PlatformWorld) -> None:
    assert _post(world, "budgets", budget_body()).status_code == 422
    _domain(world)
    created = _post(world, "budgets", budget_body())
    assert created.status_code == 201, created.text
    assert created.json()["amount"] == "1500.50" and created.json()["thresholds_percent"] == [
        50,
        80,
        100,
    ]
    for bad in (
        budget_body(budget_id="b2", thresholds_percent=[50, 50]),
        budget_body(budget_id="b3", thresholds_percent=[100, 250]),
        budget_body(budget_id="b4", amount=100.5),
        budget_body(budget_id="b5", domain_id="commercial:contoso:neurosphere:domain:nope"),
    ):
        assert _post(world, "budgets", bad).status_code == 422


def test_budget_replace_and_delete_need_if_match_and_keep_the_record(
    world: PlatformWorld,
) -> None:
    _domain(world)
    etag = _post(world, "budgets", budget_body()).headers["etag"]
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    url = f"{BASE}/budgets/fin-monthly"
    assert client.put(url, json=budget_body(amount="9"), headers=headers).status_code == 422
    replaced = client.put(url, json=budget_body(amount="9"), headers={**headers, "If-Match": etag})
    assert replaced.status_code == 200 and replaced.json()["version"] == 2
    deleted = client.delete(url, headers={**headers, "If-Match": replaced.headers["etag"]})
    assert deleted.status_code == 200 and deleted.json()["status"] == "retired"
    assert client.get(url, headers=headers).json()["status"] == "retired"
    assert client.get(f"{BASE}/budgets", headers=headers).json()["items"] == []
    assert client.get(f"{BASE}/budgets/unknown", headers=headers).status_code == 404


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST, EXPIRED_ADMIN])
def test_callers_without_customer_level_config_manage_get_403_and_a_denial(
    world: PlatformWorld, who: str
) -> None:
    client = world.composed.client()
    headers = world.auth(who)
    checks = [
        client.post(f"{BASE}/domains", json=domain_body(), headers=headers),
        client.get(f"{BASE}/domains", headers=headers),
        client.post(f"{BASE}/budgets", json=budget_body(), headers=headers),
        client.get(f"{BASE}/budgets", headers=headers),
    ]
    assert [c.status_code for c in checks] == [403, 403, 403, 403]
    assert world.records()  # denials were recorded
    assert world.repository._docs == {}  # pyright: ignore[reportPrivateUsage]
