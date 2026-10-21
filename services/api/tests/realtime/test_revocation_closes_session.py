"""Revocation closes sessions: at once on the revoking replica (fan-out), within the TTL on others.

Close code 4403. A revocation-store outage after the cached answer expires closes the socket too
(fail closed, 1013): an outage is never "not revoked".
"""

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    policy,
    principal_id_for,
    role,
)
from neurosphere_core.auth.revocation import RevocationHookRegistry
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import DependencyTransientError

from .rt_helpers import POLL, TTL, build_rig, drain, revoke, seed_domain, until_pong

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE)),
    policy(BOB, role(Role.VIEWER, FINANCE)),
)


def test_gateway_registry_is_a_push_session_registry() -> None:
    from neurosphere_api.realtime import GatewayRegistry
    from neurosphere_core.auth.revocation import PushSessionRegistry

    assert isinstance(GatewayRegistry(), PushSessionRegistry)


def test_fan_out_closes_only_the_revoked_principals_sockets_at_once() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE)
    hooks = RevocationHookRegistry()
    hooks.register_push_registry("websocket", rig.registry)
    with rig.client() as client:
        with rig.connect(client, ALICE) as alice, rig.connect(client, BOB) as bob:
            alice.send_json({"type": "subscribe", "domain_id": FINANCE})
            assert alice.receive_json()["type"] == "subscribed"
            assert until_pong(bob) == []
            assert rig.registry.session_count == 2

            assert client.portal is not None
            report = client.portal.call(hooks.fan_out, principal_id_for(ALICE))

            assert report.sessions_closed == 1
            assert report.complete
            _, code = drain(alice)
            assert code == 4403
            assert until_pong(bob) == []  # Bob is untouched
    assert rig.registry.counters.revocation_closes == 1


def test_revocation_recorded_elsewhere_closes_within_the_ttl() -> None:
    """No fan-out reaches this replica: only the per-session scope refresh can notice."""
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        assert ws.receive_json()["type"] == "subscribed"
        assert ws.receive_json()["type"] == "delta"

        revoke(rig, ALICE, at_offset=1.0)  # one second after the token was issued
        revoked_at = rig.h.clock.now
        ticks = rig.tick_until_closed(client)
        elapsed = rig.h.clock.now - revoked_at
        _, code = drain(ws)
    assert code == 4403
    assert ticks > 1, "the cached answer is honoured until it expires, not bypassed"
    assert elapsed <= TTL + POLL, "closed later than one TTL plus one poll interval"


def test_store_outage_after_cache_expiry_closes_the_socket_fail_closed() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        assert until_pong(ws) == []
        rig.revocations.fail_with(DependencyTransientError("down", reason="store_down"))
        rig.tick_until_closed(client)
        _, code = drain(ws)
    assert code == 1013


def test_idle_socket_without_subscriptions_is_still_checked() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        assert until_pong(ws) == []
        revoke(rig, BOB, at_offset=1.0)
        rig.tick_until_closed(client)
        _, code = drain(ws)
    assert code == 4403


@pytest.mark.parametrize("object_id", [ALICE, BOB])
def test_revoked_principal_cannot_open_a_session(object_id: str) -> None:
    rig = build_rig(*POLICIES)
    revoke(rig, object_id, at_offset=1.0)
    rig.h.clock.advance(1.0)
    with rig.client() as client, rig.connect(client, object_id) as ws:
        _, code = drain(ws)
    assert code == 4403
    assert rig.registry.session_count == 0
