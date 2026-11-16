"""PRP-45 item 2: every ``/api/v1/admin/system/*`` route needs the deployment-scoped admin.

``config.manage`` in an ordinary domain only (``DOMAIN_ADMIN``) is not enough; the denial is
recorded through the denial recorder (an audit record on the customer chain).
"""

from __future__ import annotations

from typing import Any

import pytest
from system_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    BASE,
    DEPLOYMENT_ADMIN,
    DOMAIN_ADMIN,
    SystemWorld,
    configure_env,
    scan_body,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _calls(world: SystemWorld, who: str) -> list[Any]:
    client = world.composed.client()
    headers = world.auth(who)
    put_headers = {**headers, "If-Match": '"absent"'}
    return [
        client.get(f"{BASE}/status", headers=headers),
        client.get(f"{BASE}/checklist", headers=headers),
        client.get(f"{BASE}/settings", headers=headers),
        client.get(f"{BASE}/settings/scan", headers=headers),
        client.put(f"{BASE}/settings/scan", json=scan_body(), headers=put_headers),
    ]


@pytest.mark.parametrize("who", [DOMAIN_ADMIN, ANALYST])
def test_callers_without_deployment_scoped_admin_get_403_and_a_recorded_denial(
    who: str,
) -> None:
    world = SystemWorld.build()
    responses = _calls(world, who)
    assert [r.status_code for r in responses] == [403] * 5
    if who == DOMAIN_ADMIN:
        assert {r.json()["reason"] for r in responses} == {"customer_scope_required"}
    denials = [r for r in world.records() if r["denial"] is not None]
    assert world.records(), "denials were recorded"
    assert len(denials) == 5
    assert world.repository._docs == {}  # pyright: ignore[reportPrivateUsage]


def test_unauthenticated_is_401() -> None:
    world = SystemWorld.build()
    response = world.composed.client().get(f"{BASE}/status")
    assert response.status_code == 401


def test_the_deployment_admin_is_allowed_everywhere() -> None:
    world = SystemWorld.build()
    statuses = [r.status_code for r in _calls(world, DEPLOYMENT_ADMIN)]
    assert statuses == [200, 200, 200, 200, 200]
