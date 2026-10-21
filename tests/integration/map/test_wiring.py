"""PRP-18 item 7: the map, replay and realtime routers are wired into the default app.

Unmarked: runs in CI, no network, no docker. The routes come from ``create_app`` (the
``REGISTERED`` hooks), not from test-supplied routers, so this fails if a hook is dropped.
The collaborators are configured through their documented ``app.state`` seams, the same calls a
deployment's startup code will make; the hot aggregates are the in-memory store here and a Cosmos
emulator in ``test_wiring_cosmos.py``.
"""

from __future__ import annotations

import asyncio

import pytest
from neurosphere_api.map import PREFIX as MAP_PREFIX
from neurosphere_api.realtime import PREFIX as REALTIME_PREFIX
from neurosphere_api.replay import PREFIX as REPLAY_PREFIX
from neurosphere_api.routers import RouterRegistry, register_default_routers
from neurosphere_core.aggregates import InMemoryAggregateStore

from .scenarios import check_delta_and_scope, check_revocation_closes_socket, check_viewport
from .support import ALICE, BOB, FINANCE, OPERATIONS, TRACES, Wiring, compose, seed_aggregates


@pytest.fixture
def wired() -> Wiring:
    store = InMemoryAggregateStore()
    asyncio.run(seed_aggregates(store, FINANCE, OPERATIONS))
    return compose(store)


def test_the_three_prefixes_are_in_the_default_registry() -> None:
    registry = RouterRegistry()
    register_default_routers(registry)
    for prefix in (MAP_PREFIX, REPLAY_PREFIX, REALTIME_PREFIX):
        assert prefix in registry.prefixes
    assert len(registry.prefixes) == len(set(registry.prefixes))


def test_map_and_replay_routes_are_in_openapi(wired: Wiring) -> None:
    paths = set(wired.h.app.openapi()["paths"])
    assert f"{MAP_PREFIX}/domains/{{domain_id}}/viewport" in paths
    assert f"{REPLAY_PREFIX}/domains/{{domain_id}}/traces" in paths
    assert f"{REPLAY_PREFIX}/domains/{{domain_id}}/traces/{{trace_id}}" in paths
    # WebSocket routes are not part of OpenAPI; the gateway is proven by the socket tests below.
    assert not [p for p in paths if p.startswith(REALTIME_PREFIX)]


def test_viewport_is_scoped(wired: Wiring) -> None:
    with wired.client() as client:
        check_viewport(wired, client)


def test_replay_is_scoped_and_read_only(wired: Wiring) -> None:
    from replay_support import TRACE  # pyright: ignore[reportMissingImports]

    with wired.client() as client:
        listing = client.get(TRACES.format(domain=FINANCE), headers=wired.h.auth(ALICE))
        assert listing.status_code == 200, listing.text
        assert TRACE in {t["trace_id"] for t in listing.json()["items"]}
        detail = client.get(f"{TRACES.format(domain=FINANCE)}/{TRACE}", headers=wired.h.auth(ALICE))
        assert detail.status_code == 200, detail.text
        assert len(detail.json()["spans"]) == 2
        for path in (TRACES.format(domain=FINANCE), f"{TRACES.format(domain=FINANCE)}/{TRACE}"):
            denied = client.get(path, headers=wired.h.auth(BOB))
            assert denied.status_code == 403, denied.text
            assert client.get(path).status_code == 401
        assert client.post(
            TRACES.format(domain=FINANCE), headers=wired.h.auth(ALICE)
        ).status_code in (
            404,
            405,
        )


def test_realtime_delta_is_scoped_to_the_permitted_domain(wired: Wiring) -> None:
    with wired.client() as client:
        check_delta_and_scope(wired, client)


def test_revocation_fan_out_closes_the_gateway_session_at_once(wired: Wiring) -> None:
    with wired.client() as client:
        check_revocation_closes_socket(wired, client)
    assert wired.registry.session_count == 0
