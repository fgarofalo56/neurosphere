"""``GET /api/v1/copilot/status`` (PRP-19 round 2 item 10): state only, any signed-in caller."""

from __future__ import annotations

from action_plane_harness import ALICE  # pyright: ignore[reportMissingImports]
from copilot_api_harness import ScriptedAdapter, say  # pyright: ignore[reportMissingImports]
from copilot_http_harness import COPILOT_PREFIX, make_http  # pyright: ignore[reportMissingImports]
from neurosphere_api.authz import undeclared_routes
from neurosphere_api.runtime.status import ComponentRegistry

URL = f"{COPILOT_PREFIX}/status"


def test_ready_when_the_copilot_is_configured() -> None:
    http = make_http(ScriptedAdapter(say("x")))
    response = http.client.get(URL, headers=http.headers(ALICE))
    assert response.status_code == 200
    assert response.json() == {"state": "ready", "reason_code": None}


def test_disabled_answers_200_when_the_copilot_is_unconfigured() -> None:
    http = make_http(ScriptedAdapter(say("x")), configured=False)
    response = http.client.get(URL, headers=http.headers(ALICE))
    assert response.status_code == 200
    assert response.json() == {"state": "disabled", "reason_code": "copilot_unconfigured"}


def test_the_composition_record_decides_the_state() -> None:
    http = make_http(ScriptedAdapter(say("x")))
    registry = ComponentRegistry()
    http.api.h.app.state.composition = registry

    registry.disabled("copilot")
    body = http.client.get(URL, headers=http.headers(ALICE)).json()
    assert body == {"state": "disabled", "reason_code": "disabled"}

    registry.failed("copilot", "copilot_endpoint_invalid")
    response = http.client.get(URL, headers=http.headers(ALICE))
    assert response.status_code == 200
    assert response.json() == {"state": "failed", "reason_code": "copilot_endpoint_invalid"}

    registry.ok("copilot")
    assert http.client.get(URL, headers=http.headers(ALICE)).json() == {
        "state": "ready",
        "reason_code": None,
    }


def test_unauthenticated_is_401_and_the_route_is_declared() -> None:
    http = make_http(ScriptedAdapter(say("x")))
    assert http.client.get(URL).status_code == 401
    assert not undeclared_routes(http.api.h.app)


def test_the_body_exposes_nothing_but_state_and_reason() -> None:
    http = make_http(ScriptedAdapter(say("x")), configured=False)
    assert set(http.client.get(URL, headers=http.headers(ALICE)).json()) == {
        "state",
        "reason_code",
    }
