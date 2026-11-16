"""PRP-44 item 3: price sheet and review policy routes."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from platform_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    BASE,
    CUSTOMER_ADMIN,
    DOMAIN_ADMIN,
    PlatformWorld,
    configure_env,
    policy_body,
    policy_settings,
    sheet_body,
    token_row,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def world() -> PlatformWorld:
    return PlatformWorld.build()


def _upload(world: PlatformWorld, body: dict[str, Any] | None = None) -> Any:
    return world.composed.client().post(
        f"{BASE}/price-sheets", json=body or sheet_body(), headers=world.auth(CUSTOMER_ADMIN)
    )


def test_upload_returns_201_summary_and_a_coverage_report_without_rows(
    world: PlatformWorld,
) -> None:
    response = _upload(world)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True and body["sheet"]["row_count"] == 3
    assert len(body["sheet"]["content_hash"]) == 64
    coverage = body["coverage"]
    assert coverage["models_priced"] == 1 and coverage["warnings"] == ["models_incomplete"]
    assert coverage["models_incomplete"][0]["model"] == "gpt-mini"
    assert "2.31" not in response.text
    assert world.prices.get("aoai-2026-11") is not None


def test_same_hash_is_idempotent_200_and_changed_content_is_409(world: PlatformWorld) -> None:
    assert _upload(world).status_code == 201
    again = _upload(world)
    assert again.status_code == 200 and again.json()["created"] is False
    changed = _upload(
        world,
        sheet_body(rows=[token_row("gpt-4.1", "input", "9"), token_row("gpt-4.1", "output", "9")]),
    )
    assert changed.status_code == 409
    assert len(world.prices.list_snapshots()) == 1


def test_sheet_for_another_cloud_synthetic_and_retail_government_are_422(
    world: PlatformWorld,
) -> None:
    assert _upload(world, sheet_body(clouds=["government"])).status_code == 422
    assert _upload(world, sheet_body(synthetic=True)).status_code == 201  # NS_ENV=local
    retail_gov = sheet_body(
        snapshot_id="retail-gov",
        source="azure_retail_prices",
        source_url="https://prices.azure.com/api/retail/prices",
        clouds=["government"],
    )
    assert _upload(world, retail_gov).status_code == 422


def test_float_price_is_refused(world: PlatformWorld) -> None:
    rows = [token_row("m", "input", "1"), token_row("m", "output", "1")]
    rows[0]["retail_price"] = 1.5
    assert _upload(world, sheet_body(rows=rows)).status_code == 422


def test_list_get_and_coverage(world: PlatformWorld) -> None:
    _upload(world)
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    listed = client.get(f"{BASE}/price-sheets", headers=headers).json()["items"]
    assert [s["snapshot_id"] for s in listed] == ["aoai-2026-11"]
    assert client.get(f"{BASE}/price-sheets/aoai-2026-11", headers=headers).status_code == 200
    coverage = client.get(f"{BASE}/price-sheets/aoai-2026-11/coverage", headers=headers).json()
    assert coverage["rows"] == 3 and coverage["rows_without_token_meter"] == 0
    assert client.get(f"{BASE}/price-sheets/nope", headers=headers).status_code == 404


def test_no_price_value_reaches_logs_or_audit(
    world: PlatformWorld, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert _upload(world).status_code == 201
    assert "2.31" not in caplog.text and "8.77" not in caplog.text
    audit = json.dumps(world.records())
    assert "price_sheet.upload" in audit and "2.31" not in audit and "8.77" not in audit


def test_review_policy_defaults_then_put_with_diff_and_version_bump(
    world: PlatformWorld,
) -> None:
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    read = client.get(f"{BASE}/review-policy", headers=headers)
    assert read.status_code == 200 and read.json()["source"] == "defaults"
    assert read.headers["etag"] == '"defaults"'
    assert (
        client.put(f"{BASE}/review-policy", json=policy_body(), headers=headers).status_code == 422
    )
    put = client.put(
        f"{BASE}/review-policy",
        json=policy_body(),
        headers={**headers, "If-Match": read.headers["etag"]},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["policy_version"] == "admin-v1" and body["version"] == 1
    assert {"path": "kind_defaults/maker_checker/sla_seconds", "before": 86400, "after": 3600} in (
        body["changes"]
    )
    stale = client.put(
        f"{BASE}/review-policy",
        json=policy_body(),
        headers={**headers, "If-Match": '"defaults"'},
    )
    assert stale.status_code == 409
    second = client.put(
        f"{BASE}/review-policy",
        json=policy_body(),
        headers={**headers, "If-Match": put.headers["etag"]},
    )
    assert second.json()["policy_version"] == "admin-v2" and second.json()["changes"] == []
    after = client.get(f"{BASE}/review-policy", headers=headers).json()
    assert after["source"] == "stored" and after["policy_version"] == "admin-v2"


@pytest.mark.parametrize(
    "settings",
    [
        policy_settings(self_approval_forbidden=False),
        policy_settings(approver_permission="catalog.curate"),
        policy_settings(sla_seconds=30),
    ],
)
def test_loosening_maker_checker_or_a_short_sla_is_422(
    world: PlatformWorld, settings: dict[str, Any]
) -> None:
    response = world.composed.client().put(
        f"{BASE}/review-policy",
        json=policy_body(settings),
        headers={**world.auth(CUSTOMER_ADMIN), "If-Match": '"defaults"'},
    )
    assert response.status_code == 422


def test_the_running_registry_is_not_hot_reloaded(world: PlatformWorld) -> None:
    client = world.composed.client()
    headers = world.auth(CUSTOMER_ADMIN)
    client.put(
        f"{BASE}/review-policy",
        json=policy_body(),
        headers={**headers, "If-Match": '"defaults"'},
    )
    assert world.policies.resolve("maker_checker").policy_version == "hitl-defaults-1"


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST])
def test_price_and_policy_routes_deny_without_customer_level_config_manage(
    world: PlatformWorld, who: str
) -> None:
    client = world.composed.client()
    headers = world.auth(who)
    codes = [
        client.post(f"{BASE}/price-sheets", json=sheet_body(), headers=headers).status_code,
        client.get(f"{BASE}/price-sheets", headers=headers).status_code,
        client.get(f"{BASE}/review-policy", headers=headers).status_code,
        client.put(
            f"{BASE}/review-policy", json=policy_body(), headers={**headers, "If-Match": '"x"'}
        ).status_code,
    ]
    assert codes == [403, 403, 403, 403]
    assert world.prices.list_snapshots() == []
