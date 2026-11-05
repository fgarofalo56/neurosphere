"""Revocation fan-out in the COMPOSED app reaches the realtime gateway (PRP-06 item 5, C13).

The authz builder publishes the composition's ``RevocationHookRegistry``; the data builder (which
runs after it) registers the realtime ``GatewayRegistry`` on it as push registry ``websocket``. A
revocation through ``RevocationService`` over the composed store and hooks therefore closes the
principal's live WebSocket at once (4403) and invalidates the composed caches (the next REST call
is 403 inside the TTL). Without the realtime gateway there are simply no push registries. In-memory
backends only; no emulator, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FakeClock,
    make_deriver,
)
from neurosphere_api.realtime import GatewayRegistry, RealtimeState
from neurosphere_api.realtime.dependencies import STATE_ATTRIBUTE
from neurosphere_api.runtime.builders import (
    REVOCATION_HOOKS,
    REVOCATION_STORE,
    BuildContext,
    BuilderSpec,
)
from neurosphere_core.auth.revocation import (
    RevocationAuditEvent,
    RevocationHookRegistry,
    RevocationOutcome,
    RevocationService,
    RevocationStore,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_core.scope import IdentityScope
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    Composed,
    builders_with_stubs,
    compose,
    composed_principal_id,
    configure_auth_env,
)
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from .data_helpers import builders_with_real_data, data_overrides

ME = "/api/v1/me/domains"
WS_URL = "/api/v1/realtime/ws"


class _AllowAll:
    async def authorize_revocation(self, actor: IdentityScope, target_principal_id: str) -> bool:
        return True


@dataclass
class _Auditor:
    events: list[RevocationAuditEvent] = field(default_factory=list)

    async def record(self, event: RevocationAuditEvent) -> None:
        self.events.append(event)


class _BrokenCloser:
    async def close_for_principal(self, principal_id: str) -> int:
        raise RuntimeError("closer down")


@dataclass
class _Captured:
    hooks: RevocationHookRegistry | None = None
    store: RevocationStore | None = None


def _with_probe(
    builders: tuple[BuilderSpec, ...], captured: _Captured, *, broken_closer: bool = False
) -> tuple[BuilderSpec, ...]:
    """Append a builder that reads what earlier builders published (and may add a closer)."""

    def probe(ctx: BuildContext) -> None:
        captured.hooks = ctx.maybe_shared(REVOCATION_HOOKS)
        captured.store = ctx.maybe_shared(REVOCATION_STORE)
        if broken_closer and captured.hooks is not None:
            captured.hooks.register_push_registry("broken", _BrokenCloser())

    return (*builders, BuilderSpec("probe", (), probe))


def _compose(
    monkeypatch: pytest.MonkeyPatch, *, realtime: bool, broken_closer: bool = False
) -> tuple[Composed, _Captured]:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    captured = _Captured()
    base = builders_with_real_data() if realtime else builders_with_stubs()
    builders = _with_probe(base, captured, broken_closer=broken_closer)
    composed = compose(data_overrides(clock), builders=builders, clock=clock)
    return composed, captured


def _service(composed: Composed, captured: _Captured, auditor: _Auditor) -> RevocationService:
    assert captured.hooks is not None, "authz must publish REVOCATION_HOOKS"
    assert captured.store is not None
    return RevocationService(
        store=captured.store,
        authorizer=_AllowAll(),
        auditor=auditor,
        hooks=captured.hooks,
        clock=composed.clock,
    )


def _actor(client: TestClient, composed: Composed) -> IdentityScope:
    """A real server-derived scope for ALICE, from the composed scope source."""
    scope_source: Any = composed.app.state.authz.scope_source
    authenticator: Any = composed.app.state.authz.authenticator
    token = composed.auth()["Authorization"].removeprefix("Bearer ")
    assert client.portal is not None
    verified = client.portal.call(authenticator.validate, token)
    return client.portal.call(scope_source.derive, verified).scope


def _revoke(client: TestClient, composed: Composed, captured: _Captured) -> RevocationOutcome:
    actor = _actor(client, composed)
    composed.clock.advance(1.0)  # revoked strictly after the token was issued
    service = _service(composed, captured, _Auditor())
    assert client.portal is not None

    async def run() -> RevocationOutcome:
        return await service.revoke(actor, composed_principal_id(ALICE), reason="offboarded")

    return client.portal.call(run)


def _drain_close_code(ws: Any) -> int | None:
    for _ in range(50):
        try:
            ws.receive_json()
        except WebSocketDisconnect as exc:
            return exc.code
    raise AssertionError("server did not close the socket")


def _until_pong(ws: Any) -> None:
    ws.send_json({"type": "ping"})
    for _ in range(50):
        if ws.receive_json().get("type") == "pong":
            return
    raise AssertionError("no pong")


def test_composed_hooks_carry_the_realtime_registry_and_both_invalidators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, captured = _compose(monkeypatch, realtime=True)
    assert composed.registry.get("realtime").state == "ok"
    assert captured.hooks is not None
    assert captured.hooks.push_registry_names == ("websocket",)
    assert captured.hooks.cache_invalidator_names == ("revocation-checker", "scope-deriver")
    realtime = getattr(composed.app.state, STATE_ATTRIBUTE)
    assert isinstance(realtime, RealtimeState)
    assert isinstance(realtime.registry, GatewayRegistry)


def test_revoking_closes_the_live_socket_and_invalidates_composed_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, captured = _compose(monkeypatch, realtime=True)
    realtime: RealtimeState = getattr(composed.app.state, STATE_ATTRIBUTE)
    token = composed.auth()["Authorization"].removeprefix("Bearer ")
    with composed.client() as client:
        # Prime the composed caches: the checker and deriver now hold "not revoked" for ALICE.
        assert client.get(ME, headers=composed.auth()).status_code == 200
        with client.websocket_connect(WS_URL, subprotocols=["ns.bearer", token]) as ws:
            _until_pong(ws)
            assert realtime.registry.session_count == 1

            outcome = _revoke(client, composed, captured)

            assert _drain_close_code(ws) == 4403
        fanout = outcome.fanout
        assert fanout.push_registries_called == 1
        assert fanout.sessions_closed == 1
        assert fanout.invalidators_called == 2
        assert fanout.complete
        # Cache invalidators ran: the revocation is seen at once, not after the TTL.
        response = client.get(ME, headers=composed.auth())
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "principal_revoked"
    assert realtime.registry.counters.revocation_closes == 1


def test_a_failing_closer_does_not_stop_the_gateway_closer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, captured = _compose(monkeypatch, realtime=True, broken_closer=True)
    assert captured.hooks is not None
    assert captured.hooks.push_registry_names == ("websocket", "broken")
    token = composed.auth()["Authorization"].removeprefix("Bearer ")
    with (
        composed.client() as client,
        client.websocket_connect(WS_URL, subprotocols=["ns.bearer", token]) as ws,
    ):
        _until_pong(ws)
        outcome = _revoke(client, composed, captured)
        assert _drain_close_code(ws) == 4403
    assert outcome.fanout.push_registries_failed == ("broken",)
    assert outcome.fanout.sessions_closed == 1
    assert outcome.fanout.invalidators_failed == ()


def test_an_injected_scope_source_still_gets_the_gateway_closer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hook registry hangs off the revocation checker, not off the composed deriver."""
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    captured = _Captured()
    source = make_deriver(InMemoryPolicyRepository(), clock)
    builders = _with_probe(builders_with_real_data(), captured)
    composed = compose(data_overrides(clock, scope_source=source), builders=builders, clock=clock)
    assert composed.app.state.authz.scope_source is source
    assert captured.hooks is not None
    assert captured.hooks.push_registry_names == ("websocket",)
    assert captured.hooks.cache_invalidator_names == ("revocation-checker",)
    report = asyncio.run(captured.hooks.fan_out(composed_principal_id(ALICE)))
    assert (report.push_registries_called, report.sessions_closed) == (1, 0)
    assert report.complete


def test_composition_without_the_gateway_has_no_closers_and_still_revokes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, captured = _compose(monkeypatch, realtime=False)  # data builder stubbed
    assert getattr(composed.app.state, STATE_ATTRIBUTE, None) is None
    assert captured.hooks is not None
    assert captured.hooks.push_registry_names == ()
    with composed.client() as client:
        assert client.get(ME, headers=composed.auth()).status_code == 200
        outcome = _revoke(client, composed, captured)
        response = client.get(ME, headers=composed.auth())
    assert outcome.fanout.push_registries_called == 0
    assert outcome.fanout.sessions_closed == 0
    assert outcome.fanout.complete
    assert response.status_code == 403
