"""The WebSocket connection handler (PRP-18 item 1).

Protocol (client -> server): ``{"type":"subscribe","domain_id":...}``, ``{"type":"unsubscribe",
"domain_id":...}``, ``{"type":"ping"}``. Server -> client: ``subscribed``, ``unsubscribed``,
``pong``, ``delta`` and ``error`` (``code`` from the ``neurosphere_core.errors`` taxonomy).

Guarantees, each enforced here:

* Authentication: the bearer token arrives in ``Sec-WebSocket-Protocol: ns.bearer, <token>``
  (browsers cannot set headers on a WebSocket) or an ``Authorization`` header (other clients);
  never both, never the query string. The PRP-06 validator and scope deriver do the work.
  Missing or invalid token closes 4401; forbidden or revoked 4403.
* The scope is derived server-side. A ``domain_id`` from the client is a REQUEST that is checked
  with ``permits(scope, data.read, domain)``; the customer is always the scope's.
* Delivery filter at SEND time: before every delta the session scope is refreshed (when older
  than the refresh period) and ``data.read`` on the domain is re-checked. A domain the scope no
  longer permits is unsubscribed and nothing is pushed.
* Revocation: ``GatewayRegistry.close_for_principal`` closes at once on this replica; the
  refresh re-runs scope derivation (which checks revocation) at least twice per TTL, so a
  revocation recorded on another replica closes the socket within the TTL.
* Fail closed: any authorization, policy or revocation error closes the socket (4401, 4403 or
  1013); no ``except`` in this module turns an error into a delivery.
* Budgets: a token bucket per session for inbound messages (``rate_limited`` error, then 4429
  after repeated breaches), a subscription cap, a message-size cap, and a send timeout that drops
  a client that cannot keep up (4429, counted). Nothing is queued: the pump sends the latest
  state per domain, so a slow client skips ticks instead of building a backlog.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import WebSocket
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import Permission, ScopeDerivation, permits
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.observability import get_logger
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError
from starlette.websockets import WebSocketDisconnect

from neurosphere_api.authz.state import STATE_ATTRIBUTE as AUTHZ_ATTRIBUTE
from neurosphere_api.authz.state import AuthzState
from neurosphere_api.realtime.budgets import TokenBucket
from neurosphere_api.realtime.dependencies import STATE_ATTRIBUTE, RealtimeState
from neurosphere_api.realtime.registry import (
    CLOSE_FORBIDDEN,
    CLOSE_RATE_LIMITED,
    CLOSE_TRY_LATER,
    CLOSE_UNAUTHENTICATED,
    Session,
    Subscription,
)

__all__ = ["BEARER_SUBPROTOCOL", "serve"]

BEARER_SUBPROTOCOL: Final = "ns.bearer"
_CLOSE_INTERNAL: Final = 1011
_CLOSE_TOO_BIG: Final = 1009
_LOG = get_logger("neurosphere_api.realtime")

DomainId = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Subscribe(_Message):
    type: Literal["subscribe"]
    domain_id: DomainId


class _Unsubscribe(_Message):
    type: Literal["unsubscribe"]
    domain_id: DomainId


class _Ping(_Message):
    type: Literal["ping"]


_CLIENT_MESSAGE: Final[TypeAdapter[_Subscribe | _Unsubscribe | _Ping]] = TypeAdapter(
    Annotated[_Subscribe | _Unsubscribe | _Ping, Field(discriminator="type")]
)


class _Stop(Exception):  # noqa: N818 - control flow, not an error condition
    """End this session: ``code`` None means the client already went away."""

    def __init__(self, code: int | None, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _error(
    code: str,
    reason: str,
    *,
    domain_id: str | None = None,
    retry_after_seconds: int | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"type": "error", "code": code, "reason": reason}
    if domain_id is not None:
        message["domain_id"] = domain_id
    if retry_after_seconds is not None:
        message["retry_after_seconds"] = retry_after_seconds
    return message


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- entry point


async def serve(websocket: WebSocket) -> None:
    """Handle one connection from accept to close."""
    gateway = getattr(websocket.app.state, STATE_ATTRIBUTE, None)
    authz = getattr(websocket.app.state, AUTHZ_ATTRIBUTE, None)
    offered = _offered_protocols(websocket)
    # Accept first so the client can read a close code; nothing is served before authentication.
    await websocket.accept(
        subprotocol=BEARER_SUBPROTOCOL if BEARER_SUBPROTOCOL in offered else None
    )
    if not isinstance(gateway, RealtimeState) or not isinstance(authz, AuthzState):
        await _close(websocket, CLOSE_TRY_LATER, "realtime_unconfigured")
        return
    handler = _Connection(websocket, gateway, authz)
    await handler.run(offered)


def _offered_protocols(websocket: WebSocket) -> list[str]:
    items: list[str] = []
    for value in websocket.headers.getlist("sec-websocket-protocol"):
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        _LOG.debug("websocket close failed")


class _Connection:
    def __init__(self, websocket: WebSocket, gateway: RealtimeState, authz: AuthzState) -> None:
        self._ws = websocket
        self._gw = gateway
        self._authz = authz
        self._cfg = gateway.settings

    # ------------------------------------------------------------------ lifecycle

    async def run(self, offered: list[str]) -> None:
        try:
            session = await self._authenticate(offered)
        except _Stop as stop:
            await _close(self._ws, stop.code or CLOSE_UNAUTHENTICATED, stop.reason)
            return
        registry = self._gw.registry
        if not registry.add(session):
            await _close(self._ws, CLOSE_RATE_LIMITED, "too_many_sessions")
            return
        tasks = [
            asyncio.ensure_future(self._guarded(self._receive_loop, session)),
            asyncio.ensure_future(self._guarded(self._pump_loop, session)),
        ]
        try:
            await session.finished.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            registry.remove(session)
        if not session.disconnected:
            await _close(self._ws, session.close_code or _CLOSE_INTERNAL, session.close_reason)

    async def _guarded(self, loop: Callable[[Session], Awaitable[None]], session: Session) -> None:
        try:
            await loop(session)
        except _Stop as stop:
            if stop.code is None:
                session.mark_disconnected()
            else:
                session.request_close(stop.code, stop.reason)
        except Exception as exc:
            _LOG.warning("realtime session failed", extra={"error_type": type(exc).__name__})
            session.request_close(_CLOSE_INTERNAL, "internal_error")

    # ------------------------------------------------------------------ authentication

    async def _authenticate(self, offered: list[str]) -> Session:
        authorization = self._authorization_value(offered)
        try:
            async with asyncio.timeout(self._authz.timeout_seconds):
                claims = await self._authz.authenticator.authenticate(authorization)
        except TimeoutError as exc:
            raise _Stop(CLOSE_TRY_LATER, "authz_timeout") from exc
        except NeuroSphereError as exc:
            raise _stop_for(exc) from exc
        except Exception as exc:
            raise _Stop(CLOSE_TRY_LATER, "authz_unavailable") from exc
        derivation = await self._derive(claims)
        scope = derivation.scope
        principal_id = scope.to_contract().principal.principal_id.root
        return Session(
            principal_id=principal_id,
            claims=claims,
            scope=scope,
            scope_at=self._gw.clock(),
            bucket=TokenBucket(
                self._cfg.message_rate_per_second, self._cfg.message_burst, self._gw.clock
            ),
        )

    def _authorization_value(self, offered: list[str]) -> str | None:
        headers = self._ws.headers.getlist("authorization")
        if len(headers) > 1:
            raise _Stop(CLOSE_UNAUTHENTICATED, "ambiguous_token")
        tokens = [p for p in offered if p != BEARER_SUBPROTOCOL]
        if BEARER_SUBPROTOCOL not in offered:
            tokens = []
        if len(tokens) > 1 or (tokens and headers):
            raise _Stop(CLOSE_UNAUTHENTICATED, "ambiguous_token")
        if tokens:
            return f"Bearer {tokens[0]}"
        return headers[0] if headers else None

    async def _derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        try:
            async with asyncio.timeout(self._authz.timeout_seconds):
                derivation = await self._authz.scope_source.derive(claims)
        except TimeoutError as exc:
            raise _Stop(CLOSE_TRY_LATER, "authz_timeout") from exc
        except NeuroSphereError as exc:
            raise _stop_for(exc) from exc
        except Exception as exc:
            raise _Stop(CLOSE_TRY_LATER, "authz_unavailable") from exc
        if not isinstance(derivation, ScopeDerivation):
            raise _Stop(CLOSE_TRY_LATER, "authz_invalid_scope")
        return derivation

    async def _refresh_scope(self, session: Session, *, force: bool = False) -> None:
        now = self._gw.clock()
        if not force and now - session.scope_at < self._gw.refresh_seconds:
            return
        derivation = await self._derive(session.claims)
        if derivation.scope.to_contract().principal.principal_id.root != session.principal_id:
            raise _Stop(CLOSE_FORBIDDEN, "principal_changed")
        session.scope = derivation.scope
        session.scope_at = now

    # ------------------------------------------------------------------ inbound

    async def _receive_loop(self, session: Session) -> None:
        while True:
            event = await self._ws.receive()
            if event["type"] == "websocket.disconnect":
                raise _Stop(None, "disconnected")
            if not session.bucket.take():
                await self._rate_limited(session, "message_rate")
                continue
            text = event.get("text")
            raw = event.get("bytes")
            size = len(text.encode()) if isinstance(text, str) else len(raw or b"")
            if size > self._cfg.max_message_bytes:
                await self._send(session, _error(InvalidSchemaError.code, "message_too_large"))
                raise _Stop(_CLOSE_TOO_BIG, "message_too_large")
            if not isinstance(text, str):
                await self._send(session, _error(InvalidSchemaError.code, "text_frames_only"))
                continue
            await self._handle(session, text)

    async def _rate_limited(self, session: Session, reason: str) -> None:
        session.violations += 1
        self._gw.registry.counters.rate_limited += 1
        await self._send(
            session,
            _error(
                RateLimitedError.code,
                reason,
                retry_after_seconds=session.bucket.retry_after_seconds,
            ),
        )
        if session.violations >= self._cfg.max_rate_violations:
            raise _Stop(CLOSE_RATE_LIMITED, "rate_limited")

    async def _handle(self, session: Session, text: str) -> None:
        try:
            message = _CLIENT_MESSAGE.validate_json(text)
        except ValidationError:
            await self._send(session, _error(InvalidSchemaError.code, "invalid_message"))
            return
        if isinstance(message, _Ping):
            await self._send(session, {"type": "pong"})
        elif isinstance(message, _Unsubscribe):
            session.subscriptions.pop(message.domain_id, None)
            await self._send(session, {"type": "unsubscribed", "domain_id": message.domain_id})
        else:
            await self._subscribe(session, message.domain_id)

    async def _subscribe(self, session: Session, domain_id: str) -> None:
        await self._refresh_scope(session)
        if not self._may_read(session, domain_id):
            await self._send(
                session,
                _error(ForbiddenError.code, "permission_missing", domain_id=domain_id),
            )
            return
        if (
            domain_id not in session.subscriptions
            and len(session.subscriptions) >= self._cfg.max_subscriptions
        ):
            self._gw.registry.counters.rate_limited += 1
            await self._send(
                session,
                _error(
                    RateLimitedError.code,
                    "subscription_limit",
                    domain_id=domain_id,
                    retry_after_seconds=1,
                ),
            )
            return
        session.subscriptions.setdefault(domain_id, Subscription())
        await self._send(session, {"type": "subscribed", "domain_id": domain_id})
        await self._deliver(session, domain_id, force=True)

    def _may_read(self, session: Session, domain_id: str) -> bool:
        now = datetime.fromtimestamp(self._gw.clock(), UTC)
        return permits(session.scope, Permission.DATA_READ, now=now, domain_id=domain_id) is True

    # ------------------------------------------------------------------ outbound

    async def _pump_loop(self, session: Session) -> None:
        while True:
            await self._gw.sleeper(self._cfg.poll_interval_seconds)
            # Refresh even with no subscriptions: an idle socket of a revoked principal closes.
            await self._refresh_scope(session)
            for domain_id in tuple(session.subscriptions):
                await self._deliver(session, domain_id, force=False)

    async def _deliver(self, session: Session, domain_id: str, *, force: bool) -> None:
        async with session.deliver_lock:
            sub = session.subscriptions.get(domain_id)
            if sub is None:
                return
            await self._refresh_scope(session)
            # Send-time filter: the CURRENT scope decides, not the one at subscribe time.
            if not self._may_read(session, domain_id):
                del session.subscriptions[domain_id]
                self._gw.registry.counters.scope_denied_deltas += 1
                await self._send(
                    session,
                    _error(ForbiddenError.code, "scope_narrowed", domain_id=domain_id),
                )
                return
            now_ts = self._gw.clock()
            now = datetime.fromtimestamp(now_ts, UTC)
            try:
                payload = await self._gw.source.poll(session.scope.customer_id, domain_id, now)
            except Exception as exc:
                if not sub.failing:
                    sub.failing = True
                    _LOG.warning("delta source failed", extra={"error_type": type(exc).__name__})
                    await self._send(
                        session,
                        _error(
                            DependencyTransientError.code,
                            "aggregates_unavailable",
                            domain_id=domain_id,
                        ),
                    )
                return
            sub.failing = False
            digest = payload.digest()
            heartbeat_due = (
                sub.last_sent_at is None or now_ts - sub.last_sent_at >= self._cfg.heartbeat_seconds
            )
            if not force and digest == sub.digest and not heartbeat_due:
                return
            session.seq += 1
            message = {
                "type": "delta",
                "domain_id": domain_id,
                "seq": session.seq,
                "nodes": [n.model_dump(mode="json") for n in payload.nodes],
                "edges": [e.model_dump(mode="json") for e in payload.edges],
                "coverage": payload.coverage.model_dump(mode="json"),
                "emitted_at": _iso(now),
            }
            await self._send(session, message, delta=True)
            sub.digest = digest
            sub.last_sent_at = now_ts

    async def _send(
        self, session: Session, message: dict[str, Any], *, delta: bool = False
    ) -> None:
        counters = self._gw.registry.counters
        try:
            async with asyncio.timeout(self._cfg.send_timeout_seconds):
                async with session.send_lock:
                    await self._ws.send_json(message)
        except TimeoutError as exc:
            counters.dropped_deltas += 1
            raise _Stop(CLOSE_RATE_LIMITED, "slow_consumer") from exc
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            raise _Stop(None, "disconnected") from exc
        if delta:
            counters.deltas_sent += 1


def _stop_for(error: NeuroSphereError) -> _Stop:
    """Map the authorization taxonomy to a close; anything else fails closed as unavailable."""
    if isinstance(error, UnauthorizedError):
        return _Stop(CLOSE_UNAUTHENTICATED, error.reason or "unauthorized")
    if isinstance(error, ForbiddenError):
        return _Stop(CLOSE_FORBIDDEN, error.reason or "forbidden")
    return _Stop(CLOSE_TRY_LATER, error.reason or "authz_unavailable")
