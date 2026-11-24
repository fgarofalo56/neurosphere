# pyright: reportAttributeAccessIssue=false
# (the world module re-exports harness names that live outside this tree's import roots)
"""Live-map secrecy (PRP-74 item 5): no shared topology snapshot between scopes, and a person's
identity string never appears in any map response body."""

import asyncio

from neurosphere_api.map.settings import MapSettings
from neurosphere_api.map.topology import TopologySource

from .test_map_topology_world import (
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    STEWARD_BOTH,
    agent_id,
    build,
    call,
    service_id,
)

_REAL = "zebulonquixote7731"  # distinctive identity string stored on the person document


def test_two_scopes_never_share_a_topology_snapshot() -> None:
    w = build()
    repo = w.api.repo
    source = TopologySource(repo, MapSettings(), clock=lambda: 1000.0)
    alice = asyncio.run(w.api.scope_of(ALICE))
    bob = asyncio.run(w.api.scope_of(BOB))
    steward = asyncio.run(w.api.scope_of(STEWARD_BOTH))
    assert alice.scope_hash != bob.scope_hash

    a_snap = asyncio.run(source.snapshot(alice, FINANCE))
    b_snap = asyncio.run(source.snapshot(bob, OPERATIONS))
    cross_a = asyncio.run(source.snapshot(alice, OPERATIONS))  # alice has no Operations role
    cross_b = asyncio.run(source.snapshot(bob, FINANCE))

    assert set(a_snap.nodes) == {agent_id("fin"), service_id("svc")}
    assert set(b_snap.nodes) == {agent_id("ops"), service_id("opssvc")}
    assert not set(a_snap.nodes) & set(b_snap.nodes)
    assert cross_a.nodes == {} and cross_b.nodes == {}, "a scope saw a domain it cannot read"
    assert a_snap is not b_snap
    assert a_snap.fingerprint != b_snap.fingerprint
    keys = {
        source.cache_key(alice, FINANCE),
        source.cache_key(bob, OPERATIONS),
        source.cache_key(alice, OPERATIONS),
        source.cache_key(bob, FINANCE),
    }
    assert len(keys) == 4, "two scopes (or two domains) share one cache key"
    assert source.cache_size == 4

    # The steward's own snapshot is separate again and cannot hand its wider view to Alice.
    s_snap = asyncio.run(source.snapshot(steward, FINANCE))
    assert set(s_snap.nodes) == set(a_snap.nodes)
    assert source.cache_key(steward, FINANCE) not in {
        source.cache_key(alice, FINANCE),
        source.cache_key(bob, FINANCE),
    }
    again = asyncio.run(source.snapshot(alice, FINANCE))
    assert again is a_snap


def test_a_persons_identity_string_never_appears_in_any_map_response() -> None:
    from map_api_helpers import person_doc  # pyright: ignore[reportMissingImports]

    w = build()
    person = person_doc(_REAL, FINANCE)
    w.api.seed(person)
    pseudonym = w.api.h.app.state.map_pseudonymizer.pseudonym("contoso", person["id"])
    probes = [
        call(w, "viewport", ALICE, FINANCE),
        call(w, "search", ALICE, FINANCE),
        call(w, "neighborhood", ALICE, FINANCE, person["id"]),
        call(w, "neighborhood", ALICE, FINANCE, agent_id("fin")),
        call(w, "impact", ALICE, FINANCE, person["id"]),
        call(w, "impact", ALICE, FINANCE, service_id("svc")),
        # the search query itself is the real string: the match must not echo it back
        w.api.h.client.get(
            f"/api/v1/map/domains/{FINANCE}/search",
            headers=w.api.h.auth(ALICE),
            params={"q": _REAL},
        ),
        # the person is a foreign-domain node for Bob: a 404 must not echo it either
        call(w, "neighborhood", BOB, OPERATIONS, person["id"]),
        call(w, "impact", BOB, OPERATIONS, person["id"]),
    ]
    seen_pseudonym = False
    for response in probes:
        text = response.text.replace(response.json().get("instance", "") or "", "")
        assert _REAL not in text.lower(), response.request.url
        assert person["id"] not in text, response.request.url
        assert "psn_" not in text, response.request.url
        seen_pseudonym = seen_pseudonym or pseudonym in text
    assert seen_pseudonym, "positive control: the person never appeared, by pseudonym, anywhere"
