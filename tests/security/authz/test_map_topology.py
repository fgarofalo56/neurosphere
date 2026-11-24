# pyright: reportAttributeAccessIssue=false
# (the world module re-exports harness names that live outside this tree's import roots)
"""Live-map routes (PRP-74 item 5): ABAC negatives for viewport, search, neighbourhood, impact.

Every denied case expects 403 with a recorded denial (domain and permission), every cross-domain
node case expects the single not-found 404, and no denied body carries data or the other
domain's ids. No case is skipped.
"""

import pytest

from .test_map_topology_world import (
    ALICE,
    BOB,
    EXPIRING,
    EXPIRY_SECONDS,
    FINANCE,
    NOROLE,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    ROUTES,
    World,
    agent_id,
    build,
    call,
    service_id,
)

_NODE = {"neighborhood": agent_id("fin"), "impact": service_id("svc")}
_OTHER_NODE = {"neighborhood": agent_id("ops"), "impact": service_id("opssvc")}
_NODE_ROUTES = ("neighborhood", "impact")
_LEAKS = (agent_id("fin"), agent_id("ops"), service_id("svc"), service_id("opssvc"))


@pytest.fixture(scope="module")
def world() -> World:
    return build()


def _node(route: str) -> str | None:
    return _NODE.get(route)


def _assert_denied(world: World, response: object, domain: str, before: int) -> None:
    status = response.status_code  # type: ignore[attr-defined]
    text = response.text  # type: ignore[attr-defined]
    assert status == 403, text
    for secret in _LEAKS:
        assert secret not in text.replace(response.json().get("instance", ""), "")  # type: ignore[attr-defined]
    assert "nodes" not in response.json()  # type: ignore[attr-defined]
    new = world.denials.attempts[before:]
    assert len(new) == 1, "a denied request must record exactly one denial"
    assert new[0].permission == "data.read"
    assert new[0].domain_id == domain


@pytest.mark.parametrize("route", ROUTES)
def test_no_token_is_401(world: World, route: str) -> None:
    assert call(world, route, None, FINANCE, _node(route)).status_code == 401


@pytest.mark.parametrize("route", ROUTES)
def test_principal_with_no_role_is_denied(world: World, route: str) -> None:
    before = len(world.denials.attempts)
    response = call(world, route, NOROLE, FINANCE, _node(route))
    _assert_denied(world, response, FINANCE, before)


@pytest.mark.parametrize("route", ROUTES)
def test_viewer_of_another_domain_is_denied(world: World, route: str) -> None:
    before = len(world.denials.attempts)
    response = call(world, route, BOB, FINANCE, _node(route))
    _assert_denied(world, response, FINANCE, before)
    before = len(world.denials.attempts)
    response = call(world, route, ALICE, OPERATIONS, _OTHER_NODE.get(route))
    _assert_denied(world, response, OPERATIONS, before)


@pytest.mark.parametrize("route", ROUTES)
def test_wrong_customer_domain_is_denied(world: World, route: str) -> None:
    before = len(world.denials.attempts)
    response = call(world, route, ALICE, OTHER_CUSTOMER_FINANCE, _node(route))
    _assert_denied(world, response, OTHER_CUSTOMER_FINANCE, before)


@pytest.mark.parametrize("route", ROUTES)
def test_expired_scope_is_denied_after_the_role_lapses(route: str) -> None:
    w = build()
    ok = call(w, route, EXPIRING, FINANCE, _node(route))
    assert ok.status_code == 200, ok.text
    w.api.h.clock.advance(EXPIRY_SECONDS * 2)
    before = len(w.denials.attempts)
    response = call(w, route, EXPIRING, FINANCE, _node(route))
    _assert_denied(w, response, FINANCE, before)


@pytest.mark.parametrize("route", ROUTES)
def test_expired_token_is_401(world: World, route: str) -> None:
    response = call(world, route, ALICE, FINANCE, _node(route), exp=1)
    assert response.status_code == 401


@pytest.mark.parametrize("route", _NODE_ROUTES)
def test_node_in_another_domain_is_the_same_404_as_a_missing_node(world: World, route: str) -> None:
    other = call(world, route, ALICE, FINANCE, _OTHER_NODE[route])
    missing = call(world, route, ALICE, FINANCE, agent_id("does-not-exist"))
    assert other.status_code == 404, other.text
    assert missing.status_code == 404
    keys = ("type", "title", "status", "detail", "code", "reason", "retryable")
    assert {k: other.json().get(k) for k in keys} == {k: missing.json().get(k) for k in keys}
    assert _OTHER_NODE[route] not in other.text.replace(other.json().get("instance", ""), "")


@pytest.mark.parametrize("route", ROUTES)
def test_allowed_reader_sees_only_own_domain(world: World, route: str) -> None:
    response = call(world, route, ALICE, FINANCE, _node(route))
    assert response.status_code == 200, response.text
    assert agent_id("ops") not in response.text
    assert service_id("opssvc") not in response.text
