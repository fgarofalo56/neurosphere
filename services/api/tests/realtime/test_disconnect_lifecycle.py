"""A client that leaves abruptly must never make the endpoint end cancelled or leak sessions.

The Starlette test client cancels the app task right after it delivers ``websocket.disconnect``;
the endpoint's cleanup (cancel and await the receive/pump tasks) has to survive that race.
"""

import pytest
from authz.authz_helpers import BOB, FINANCE, policy, role  # pyright: ignore[reportMissingImports]
from neurosphere_core.auth.scope import Role
from starlette.websockets import WebSocketDisconnect

from .rt_helpers import build_rig, seed_domain

POLICIES = (policy(BOB, role(Role.VIEWER, FINANCE)),)


def test_repeated_abrupt_disconnects_end_cleanly_and_release_sessions() -> None:
    for _ in range(40):  # a fresh rig each time: asyncio primitives bind to one event loop
        rig = build_rig(*POLICIES)
        seed_domain(rig.aggregates, FINANCE)
        with rig.client() as client, rig.connect(client, BOB) as ws:
            ws.send_json({"type": "subscribe", "domain_id": FINANCE})
            assert ws.receive_json()["type"] == "subscribed"
        assert rig.registry.session_count == 0


def test_disconnect_right_after_connect_ends_cleanly() -> None:
    for _ in range(40):
        rig = build_rig(*POLICIES)
        with rig.client() as client, rig.connect(client, BOB):
            pass
        assert rig.registry.session_count == 0


def test_unexpected_failure_closes_1011_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret detail must not leak")

    monkeypatch.setattr("neurosphere_api.realtime.gateway._Connection._deliver", boom)
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        assert ws.receive_json()["type"] == "subscribed"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1011
    assert closed.value.reason == "internal_error"
    assert rig.registry.session_count == 0
