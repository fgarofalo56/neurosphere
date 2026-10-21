"""Gateway authentication: subprotocol or header token, never the query string; fail closed."""

import uuid
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    policy,
    role,
)
from neurosphere_api.authz import configure_authz
from neurosphere_api.realtime import configure_realtime
from neurosphere_api.realtime.router import PREFIX, build_router
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import Role, ScopeDerivation
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from starlette.testclient import TestClient

from .rt_helpers import WS_URL, build_rig, drain, until_pong

POLICIES = (policy(ALICE, role(Role.VIEWER, FINANCE)),)


def test_subprotocol_token_is_accepted_and_the_subprotocol_echoed() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        assert ws.accepted_subprotocol == "ns.bearer"
        assert until_pong(ws) == []


def test_authorization_header_is_accepted_for_non_browser_clients() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client:
        with client.websocket_connect(WS_URL, headers=rig.h.auth(ALICE)) as ws:
            assert until_pong(ws) == []


@pytest.mark.parametrize("mode", ["none", "garbage", "both", "query", "bare_protocol"])
def test_missing_or_invalid_token_closes_4401(mode: str) -> None:
    rig = build_rig(*POLICIES)
    token = rig.h.token(ALICE)
    garbage = uuid.uuid4().hex
    kwargs: dict[str, Any] = {}
    url = WS_URL
    if mode == "garbage":
        kwargs["subprotocols"] = ["ns.bearer", garbage]
    elif mode == "both":
        kwargs["subprotocols"] = ["ns.bearer", token]
        kwargs["headers"] = rig.h.auth(ALICE)
    elif mode == "query":
        url = f"{WS_URL}?access_token={token}"  # a query string is never a token source
    elif mode == "bare_protocol":
        kwargs["subprotocols"] = ["ns.bearer"]
    with rig.client() as client, client.websocket_connect(url, **kwargs) as ws:
        _, code = drain(ws)
    assert code == 4401
    assert rig.registry.session_count == 0


def test_unconfigured_gateway_fails_closed() -> None:
    rig = build_rig(*POLICIES)
    del rig.h.app.state.realtime
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        _, code = drain(ws)
    assert code == 1013


class _Failing:
    """Scope source whose outcome is chosen by the test; ``derive`` never returns a scope."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ForbiddenError("no", reason="principal_revoked"), 4403),
        (RuntimeError("boom"), 1013),
        (InvalidSchemaError("odd"), 1013),
    ],
)
def test_policy_or_scope_errors_close_the_socket_never_allow(
    error: Exception, expected: int
) -> None:
    rig = build_rig(*POLICIES)
    configure_authz(
        rig.h.app, authenticator=rig.h.validator, scope_source=_Failing(error), clock=rig.h.clock
    )
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        _, code = drain(ws)
    assert code == expected
    assert rig.registry.session_count == 0


def test_no_authz_configuration_fails_closed() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(build_router(), prefix=PREFIX)
    configure_realtime(app, aggregate_reader=InMemoryAggregateStore())
    with TestClient(app) as client, client.websocket_connect(WS_URL) as ws:
        _, code = drain(ws)
    assert code == 1013


def test_expired_token_is_rejected_at_the_next_scope_refresh() -> None:
    rig = build_rig(*POLICIES)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        assert until_pong(ws) == []
        rig.h.clock.advance(3 * 3600)  # past the dev token lifetime
        rig.tick(client)
        _, code = drain(ws)
    assert code == 4401


def test_configure_realtime_requires_exactly_one_source() -> None:
    from fastapi import FastAPI

    with pytest.raises(InvalidSchemaError):
        configure_realtime(FastAPI())
    with pytest.raises(InvalidSchemaError):
        configure_realtime(
            FastAPI(),
            aggregate_reader=InMemoryAggregateStore(),
            source=object(),  # type: ignore[arg-type]
        )


def test_websocket_route_declares_data_read_for_the_route_inventory() -> None:
    from neurosphere_api.authz.routes import route_inventory, undeclared_routes

    rig = build_rig(*POLICIES)
    entries = [e for e in route_inventory(rig.h.app) if e.path == WS_URL]
    assert [(e.methods, e.permissions) for e in entries] == [(("WEBSOCKET",), ("data.read",))]
    assert undeclared_routes(rig.h.app) == ()
