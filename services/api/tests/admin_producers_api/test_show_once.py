"""PRP-41 item 3: the secret is shown once and never logged or listed."""

from __future__ import annotations

import logging

import pytest
from producer_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    CUSTOMER_ADMIN,
    ProducerWorld,
    configure_env,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_secret_is_in_exactly_one_response_and_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = ProducerWorld.build()
    c = world.composed.client()
    h = world.auth(CUSTOMER_ADMIN)
    body = {"producer_id": "p-once", "cloud": "commercial", "sources": {"s1": "gateway"}}
    with caplog.at_level(logging.DEBUG):
        created = c.post(BASE, json=body, headers=h)
        secret = created.json()["secret"]
        others = [
            c.get(f"{BASE}/p-once", headers=h),
            c.get(BASE, headers=h),
            c.post(f"{BASE}/p-once/disable", headers={**h, "If-Match": created.headers["etag"]}),
        ]
    assert all(secret not in r.text for r in others)
    assert secret not in caplog.text
    assert created.json()["secret_sha256"] not in caplog.text
