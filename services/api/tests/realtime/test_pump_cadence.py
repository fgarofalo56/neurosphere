"""PRP-18 round 2 item 3: the pump sleeps no longer than the scope refresh period."""

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    policy,
    role,
)
from neurosphere_core.auth.scope import Role

from .rt_helpers import build_rig

POLICIES = (policy(ALICE, role(Role.VIEWER, FINANCE)),)


def test_pump_sleeps_the_refresh_period_when_poll_is_longer() -> None:
    # poll 10 s, TTL 4 s -> refresh 2 s (half the TTL): the pump must wake at 2 s, not 10 s
    rig = build_rig(*POLICIES, ttl=4.0, poll_interval_seconds=10.0, scope_refresh_seconds=5.0)
    assert rig.settings.effective_refresh_seconds(4.0) == 2.0
    with rig.client() as client, rig.connect(client, ALICE):
        rig.tick(client)
        assert rig.ticker.requested
        assert set(rig.ticker.requested) == {2.0}


def test_pump_keeps_the_poll_interval_when_it_is_shorter() -> None:
    rig = build_rig(*POLICIES, ttl=60.0, poll_interval_seconds=0.5, scope_refresh_seconds=5.0)
    with rig.client() as client, rig.connect(client, ALICE):
        rig.tick(client)
        assert set(rig.ticker.requested) == {0.5}


def test_zero_refresh_period_never_spins() -> None:
    rig = build_rig(*POLICIES, ttl=60.0, poll_interval_seconds=3.0, scope_refresh_seconds=0.0)
    with rig.client() as client, rig.connect(client, ALICE):
        rig.tick(client)
        assert set(rig.ticker.requested) == {3.0}
