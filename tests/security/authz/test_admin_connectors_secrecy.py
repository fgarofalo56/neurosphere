"""Secrecy of the connector admin API (PRP-42 item 5): no reference or value leaves by a side door.

A created config carries a Key Vault reference. The vault host, secret name and any value a caller
tried to smuggle in must not appear in log output, in audit payloads, in the text of a refused
request or in the OpenAPI document. (The authorised admin's own response may name the reference:
it identifies a secret, it is not one; no secret value exists anywhere in the store.)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from .test_admin_connectors import (
    BASE,
    CONTROL_ADMIN_OID,
    VAULT,
    Plane,
    _bearer,
    body,
    cworld,  # noqa: F401  (fixture)
)
from .world import World

LEAK = "do-not-leak-7d41"
MARKERS = ("ns-kv", "producer-key", LEAK)


def _audit_text(world: World) -> str:
    dep = world["contoso"]
    docs = [
        doc
        for (chain, _doc_id), doc in dep.audit_store._docs.items()  # pyright: ignore[reportPrivateUsage]
        if chain.endswith("admin-config")
    ]
    return json.dumps(docs, default=str)


def _assert_clean(text: str) -> None:
    for marker in MARKERS:
        assert marker not in text, f"{marker!r} leaked"


def test_created_config_leaks_nothing_to_logs_or_audit(
    cworld: tuple[World, dict[str, Plane]],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world, _ = cworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    with caplog.at_level(logging.DEBUG):
        created = dep.client.post(BASE, headers=headers, json=body())
        assert created.status_code == 201, created.text
        etag = created.headers["etag"]
        dep.client.get(f"{BASE}/gateway-main", headers=headers)
        dep.client.post(f"{BASE}/gateway-main/disable", headers={**headers, "If-Match": etag})
    _assert_clean(caplog.text)
    audit = _audit_text(world)
    assert "connector.create" in audit and "connector.disable" in audit
    _assert_clean(audit)


@pytest.mark.parametrize(
    "payload",
    [
        {"password": LEAK},
        {"settings": {"api_base_url": f"https://u:{LEAK}@api.example.test"}},
        {"settings": {"api_base_url": "https://api.example.test", "api_token": LEAK}},
        {"credential": {"kind": "key_vault_secret", "secret_value": LEAK, "secret_uri": VAULT}},
        {
            "credential": {
                "kind": "key_vault_secret",
                "secret_uri": f"https://{LEAK}.vault.azure.net/x",
            }
        },
    ],
)
def test_refused_requests_echo_nothing(
    cworld: tuple[World, dict[str, Plane]],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    payload: dict[str, Any],
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    with caplog.at_level(logging.DEBUG):
        response = dep.client.post(
            BASE, headers=_bearer(dep, CONTROL_ADMIN_OID), json=body(**payload)
        )
    assert response.status_code == 422, response.text
    for text in (response.text, caplog.text, _audit_text(world)):
        assert LEAK not in text and "producer-key" not in text and "ns-kv" not in text
    assert planes["contoso"].repository._docs == {}  # pyright: ignore[reportPrivateUsage]


def test_openapi_document_has_no_concrete_reference(
    cworld: tuple[World, dict[str, Plane]],  # noqa: F811
) -> None:
    world, _ = cworld
    schema = json.dumps(world["contoso"].app.openapi())
    _assert_clean(schema)
