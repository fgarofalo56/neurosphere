"""``GET /api/v1/me/domains`` (PRP-28 item 1): real authz stack, in-memory catalog repository."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    FINANCE,
    GOV_FINANCE,
    HR,
    NOBODY,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    Harness,
    harness,
    policy,
    role,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_entity

URL = "/api/v1/me/domains"
_SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas"
STEWARD = "a1b2c3d4-0000-4000-8000-000000000001"


def _domain_doc(domain_id: str, display_name: str) -> dict[str, Any]:
    path = _SCHEMAS / "catalog/v1/examples/valid/domain.minimal-and-typical.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(
        id=domain_id,
        customer_id="contoso",
        version=1,
        etag="caller-etag",
        display_name=display_name,
    )
    return raw


def _make() -> Harness:
    return harness(
        policy(ALICE, role(Role.VIEWER, FINANCE), role(Role.ANALYST, OPERATIONS)),
        policy(BOB, role(Role.VIEWER, HR)),
        # Only an auditor: holds audit/evidence but never data.read anywhere.
        policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
        policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS, HR)),
        # Roles naming another customer's and another cloud's domains must never surface.
        policy(
            NOBODY,
            role(Role.VIEWER, FINANCE, OTHER_CUSTOMER_FINANCE, GOV_FINANCE),
            memberships=(FINANCE, OTHER_CUSTOMER_FINANCE, GOV_FINANCE),
        ),
    )


def _seed_catalog(h: Harness, *docs: dict[str, Any]) -> None:
    repo = InMemoryCatalogRepository()
    h.app.state.catalog_repository = repo

    async def run() -> None:
        claims = await h.validator.authenticate(h.auth(STEWARD)["Authorization"])
        scope = (await h.deriver.derive(claims)).scope
        for doc in docs:
            await repo.create_entity(scope, parse_entity(doc))

    asyncio.run(run())


def test_unauthenticated_is_401() -> None:
    assert _make().client.get(URL).status_code == 401


def test_only_data_read_domains_are_listed_with_derived_names() -> None:
    h = _make()
    response = h.client.get(URL, headers=h.auth(ALICE))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["domain_id"] for i in items] == [FINANCE, OPERATIONS]
    assert [i["display_name"] for i in items] == ["Finance", "Operations"]
    assert {i["display_name_source"] for i in items} == {"derived"}
    assert {i["cloud"] for i in items} == {"commercial"}
    by_id = {i["domain_id"]: i["permissions"] for i in items}
    assert by_id[FINANCE] == ["data.read"]
    assert "report.create" in by_id[OPERATIONS]
    assert HR not in by_id


def test_other_users_see_only_their_own_domains() -> None:
    h = _make()
    response = h.client.get(URL, headers=h.auth(BOB))
    assert [i["domain_id"] for i in response.json()["items"]] == [HR]


def test_cross_customer_and_cross_cloud_domains_never_appear() -> None:
    h = _make()
    response = h.client.get(URL, headers=h.auth(NOBODY))
    assert response.status_code == 200, response.text
    ids = [i["domain_id"] for i in response.json()["items"]]
    assert ids == [FINANCE]
    assert OTHER_CUSTOMER_FINANCE not in ids
    assert GOV_FINANCE not in ids


def test_zero_readable_domains_is_403_forbidden() -> None:
    h = _make()
    response = h.client.get(URL, headers=h.auth(CAROL))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(
    "params",
    [
        {"domain_id": HR},
        {"customer_id": "fabrikam"},
        {"domain_id": OTHER_CUSTOMER_FINANCE, "customer_id": "fabrikam"},
    ],
)
def test_caller_supplied_identifiers_are_ignored(params: dict[str, str]) -> None:
    h = _make()
    response = h.client.get(URL, headers=h.auth(ALICE), params=params)
    assert response.status_code == 200
    assert [i["domain_id"] for i in response.json()["items"]] == [FINANCE, OPERATIONS]


def test_body_identifiers_are_ignored() -> None:
    h = _make()
    response = h.client.request(
        "GET", URL, headers=h.auth(ALICE), json={"domain_id": HR, "customer_id": "fabrikam"}
    )
    assert response.status_code == 200
    assert [i["domain_id"] for i in response.json()["items"]] == [FINANCE, OPERATIONS]


def test_catalog_display_name_wins_and_missing_entries_fall_back() -> None:
    h = _make()
    _seed_catalog(h, _domain_doc(FINANCE, "Corporate Finance"))
    items = h.client.get(URL, headers=h.auth(ALICE)).json()["items"]
    by_id = {i["domain_id"]: i for i in items}
    assert by_id[FINANCE]["display_name"] == "Corporate Finance"
    assert by_id[FINANCE]["display_name_source"] == "catalog"
    assert by_id[OPERATIONS]["display_name"] == "Operations"
    assert by_id[OPERATIONS]["display_name_source"] == "derived"


def test_sorted_by_display_name_not_by_id() -> None:
    h = _make()
    _seed_catalog(h, _domain_doc(FINANCE, "Zeta"), _domain_doc(OPERATIONS, "Alpha"))
    items = h.client.get(URL, headers=h.auth(ALICE)).json()["items"]
    assert [i["display_name"] for i in items] == ["Alpha", "Zeta"]
    assert [i["domain_id"] for i in items] == [OPERATIONS, FINANCE]


def test_catalog_entries_for_unreadable_domains_do_not_leak() -> None:
    h = _make()
    _seed_catalog(h, _domain_doc(HR, "Human Resources"))
    items = h.client.get(URL, headers=h.auth(ALICE)).json()["items"]
    assert HR not in {i["domain_id"] for i in items}
    assert "Human Resources" not in {i["display_name"] for i in items}
