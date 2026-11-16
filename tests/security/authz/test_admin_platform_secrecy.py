"""Secrecy of the platform admin API (PRP-44 item 6): no price value or policy body leaves.

Price rows are commercially sensitive and a policy body is operator configuration: neither may
appear in log output, in audit payloads, in the text of a refused request or in the OpenAPI
document (which carries schemas, never a concrete value).
"""

from __future__ import annotations

import json
import logging

import pytest

from .test_admin_platform import (
    BASE,
    CONTROL_ADMIN_OID,
    Plane,
    _bearer,
    policy_body,
    pworld,  # noqa: F401  (fixture)
    sheet_body,
)
from .world import World

PRICES = ("1.23", "9.8765", "4.4321")
POLICY_MARKERS = ("14400", "7200", "action.approve")


def _audit_text(world: World) -> str:
    dep = world["contoso"]
    docs = [
        doc
        for (chain, _doc_id), doc in dep.audit_store._docs.items()  # pyright: ignore[reportPrivateUsage]
        if chain.endswith("admin-config")
    ]
    return json.dumps(docs, default=str)


def _priced_sheet() -> dict[str, object]:
    body = sheet_body()
    rows = body["rows"]
    assert isinstance(rows, list)
    rows[0]["retail_price"] = "9.8765"
    rows[1]["retail_price"] = "4.4321"
    return body


def test_price_upload_leaks_no_price_to_logs_audit_or_listings(
    pworld: tuple[World, dict[str, Plane]],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world, _ = pworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    with caplog.at_level(logging.DEBUG):
        created = dep.client.post(f"{BASE}/price-sheets", headers=headers, json=_priced_sheet())
        assert created.status_code == 201, created.text
        again = dep.client.post(f"{BASE}/price-sheets", headers=headers, json=_priced_sheet())
        listed = dep.client.get(f"{BASE}/price-sheets", headers=headers)
        coverage = dep.client.get(f"{BASE}/price-sheets/sheet-1/coverage", headers=headers)
    audit = _audit_text(world)
    assert "price_sheet.upload" in audit
    for text in (caplog.text, audit, created.text, again.text, listed.text, coverage.text):
        for price in PRICES[1:]:
            assert price not in text, f"{price} leaked"


def test_refused_price_upload_echoes_no_price(
    pworld: tuple[World, dict[str, Plane]],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world, planes = pworld
    dep = world["contoso"]
    body = _priced_sheet()
    body["clouds"] = ["government"]
    with caplog.at_level(logging.DEBUG):
        response = dep.client.post(
            f"{BASE}/price-sheets", headers=_bearer(dep, CONTROL_ADMIN_OID), json=body
        )
    assert response.status_code == 422, response.text
    for text in (response.text, caplog.text, _audit_text(world)):
        assert "9.8765" not in text and "4.4321" not in text
    assert planes["contoso"].prices.list_snapshots() == []


def test_policy_write_keeps_the_body_out_of_logs_and_audit(
    pworld: tuple[World, dict[str, Plane]],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world, _ = pworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    with caplog.at_level(logging.DEBUG):
        put = dep.client.put(
            f"{BASE}/review-policy",
            headers={**headers, "If-Match": '"defaults"'},
            json=policy_body(),
        )
    assert put.status_code == 200, put.text
    audit = _audit_text(world)
    assert "review_policy.replace" in audit
    for text in (caplog.text, audit):
        for marker in POLICY_MARKERS:
            assert marker not in text, f"{marker!r} leaked"


def test_openapi_document_has_no_concrete_price_or_policy_value(
    pworld: tuple[World, dict[str, Plane]],  # noqa: F811
) -> None:
    world, _ = pworld
    schema = json.dumps(world["contoso"].app.openapi())
    for price in PRICES:
        assert price not in schema
