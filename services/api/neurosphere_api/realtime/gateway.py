"""The WebSocket connection handler (PRP-18 item 1).

Protocol (client -> server): ``{"type":"subscribe","domain_id":...}``, ``{"type":"unsubscribe",
"domain_id":...}``, ``{"type":"ping"}``. Server -> client: ``subscribed``, ``unsubscribed``,
``pong``, ``delta``, ``topology`` (PRP-74: the ids that changed, refetch the viewport) and
``error`` (``code`` from the ``neurosphere_core.errors`` taxonomy).

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
  revocation recorded on another replica closes the socket within the TTL plus one interval
  (the pump sleeps ``min(poll interval, refresh period)``).
* Fail closed: any authorization, policy or revocation error closes the socket (4401, 4403 or
  1013); no ``except`` in this module turns an error into a delivery.
* Budgets: a token bucket per session for inbound messages (``rate_limited`` error, then 4429
  after repeated breaches), a subscription cap, a message-size cap, and a send timeout that drops
  a client that cannot keep up (4429, counted). Nothing is queued: the pump sends the latest
  state per domain, so a slow client skips ticks instead of building a backlog.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import WebSocket
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import Permission, ScopeDerivation, permits
from neurosphere_core.catalog import CatalogRepository
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
from neurosphere_api.map.topology import TopologySnapshot, TopologySource, diff_snapshots
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
from neurosphere_api.realtime.source import DeltaPayload, expand_model_nodes

__all__ = ["BEARER_SUBPROTOCOL", "serve"]

BEARER_SUBPROTOCOL: Final = "ns.bearer"
TOPOLOGY_ATTRIBUTE: Final = "map_topology"
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


async def _reap(tasks: Sequence["asyncio.Future[None]"]) -> bool:
    """Cancel ``tasks`` and wait until every one has finished.

    Shielded so a cancellation of the caller cannot abandon a half-cancelled child; returns True
    when the caller was cancelled while waiting (the caller decides whether to re-raise).
    """
    for task in tasks:
        task.cancel()
    pending = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while True:
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            cancelled = True
            if pending.done():
                return cancelled
        else:
            return cancelled


class _Connection:
    def __init__(self, websocket: WebSocket, gateway: RealtimeState, authz: AuthzState) -> None:
        self._ws = websocket
        self._gw = gateway
        self._authz = authz
        self._cfg = gateway.settings
        # Per-connection topology state: the snapshot this session last saw and when it last
        # polled, per subscribed domain. A fresh subscription starts with neither (baseline).
        self._topology_seen: dict[str, TopologySnapshot] = {}
        self._topology_polled: dict[str, float] = {}

    def _topology(self) -> TopologySource | None:
        """The topology source, built lazily from ``app.state.catalog_repository`` and cached on
        ``app.state.map_topology``; ``None`` when the switch is off or no repository is wired."""
        if not self._gw.map_settings.topology_enabled:
            return None
        state = self._ws.app.state
        existing = getattr(state, TOPOLOGY_ATTRIBUTE, None)
        if isinstance(existing, TopologySource):
            return existing
        repository = getattr(state, "catalog_repository", None)
        if not isinstance(repository, CatalogRepository):
            return None
        source = TopologySource(repository, self._gw.map_settings, clock=self._gw.clock)
        setattr(state, TOPOLOGY_ATTRIBUTE, source)
        return source

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
        cancelled = False
        try:
            try:
                await session.finished.wait()
            except asyncio.CancelledError:
                cancelled = True
            # Child tasks are always cancelled AND awaited, even if we are cancelled meanwhile.
            cancelled = await _reap(tasks) or cancelled
        finally:
            registry.remove(session)
        if session.disconnected:
            # The peer is gone and cleanup is complete. A cancellation that raced the disconnect
            # (a server shutting the connection task down just as the client left) has nothing
            # left to interrupt, so the endpoint returns normally instead of dying cancelled.
            return
        if cancelled:
            raise asyncio.CancelledError  # a real cancel of this endpoint is never swallowed
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
            self._forget_topology(message.domain_id)
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
        self._forget_topology(domain_id)
        await self._deliver(session, domain_id, force=True)
        await self._deliver_topology(session, domain_id, baseline=True)

    def _forget_topology(self, domain_id: str) -> None:
        self._topology_seen.pop(domain_id, None)
        self._topology_polled.pop(domain_id, None)

    def _may_read(self, session: Session, domain_id: str) -> bool:
        now = datetime.fromtimestamp(self._gw.clock(), UTC)
        return permits(session.scope, Permission.DATA_READ, now=now, domain_id=domain_id) is True

    # ------------------------------------------------------------------ outbound

    async def _pump_loop(self, session: Session) -> None:
        # Sleep no longer than the scope refresh period, so the refresh cadence holds even when
        # the poll interval is longer than half the revocation TTL. A zero refresh period means
        # "refresh every poll", never a busy loop.
        refresh = self._gw.refresh_seconds
        interval = (
            min(self._cfg.poll_interval_seconds, refresh)
            if refresh > 0
            else self._cfg.poll_interval_seconds
        )
        while True:
            await self._gw.sleeper(interval)
            # Refresh even with no subscriptions: an idle socket of a revoked principal closes.
            await self._refresh_scope(session)
            for domain_id in tuple(session.subscriptions):
                await self._deliver(session, domain_id, force=False)
                await self._deliver_topology(session, domain_id, baseline=False)

    async def _deliver_topology(self, session: Session, domain_id: str, *, baseline: bool) -> None:
        """Push a ``topology`` notice when the scope's view of the domain changed (PRP-74).

        Same send-time rule as deltas: the CURRENT scope must still read the domain, else the
        subscription is dropped with ``scope_narrowed``. The first look (``baseline``) only
        records the snapshot. The snapshot is taken under this session's scope, so the notice
        never names an id the scope cannot read.
        """
        source = self._topology()
        if source is None:
            return
        cfg = self._gw.map_settings
        async with session.deliver_lock:
            if domain_id not in session.subscriptions:
                return
            await self._refresh_scope(session)
            if not self._may_read(session, domain_id):
                del session.subscriptions[domain_id]
                self._forget_topology(domain_id)
                self._gw.registry.counters.scope_denied_deltas += 1
                await self._send(
                    session,
                    _error(ForbiddenError.code, "scope_narrowed", domain_id=domain_id),
                )
                return
            now_ts = self._gw.clock()
            last = self._topology_polled.get(domain_id)
            if not baseline and last is not None and now_ts - last < cfg.topology_poll_seconds:
                return
            try:
                current = await source.snapshot(session.scope, domain_id)
            except Exception as exc:
                _LOG.warning("topology source failed", extra={"error_type": type(exc).__name__})
                return
            self._topology_polled[domain_id] = now_ts
            previous = self._topology_seen.get(domain_id)
            self._topology_seen[domain_id] = current
            if baseline or previous is None:
                return
            now = datetime.fromtimestamp(now_ts, UTC)
            change = diff_snapshots(previous, current, domain_id, now)
            if change is None:
                return
            session.seq += 1
            message = {
                "type": "topology",
                "seq": session.seq,
                **change.model_dump(mode="json"),
                "emitted_at": _iso(now),
            }
            await self._send(session, message, delta=True)

    async def _with_deployment_ids(
        self, session: Session, domain_id: str, payload: DeltaPayload
    ) -> DeltaPayload:
        """Rewrite model nodes to deployment ids from a snapshot under THIS session's scope."""
        if not any(n.kind == "model" for n in payload.nodes):
            return payload
        source = self._topology()
        if source is None:
            return expand_model_nodes(payload, None)
        try:
            snapshot = await source.snapshot(session.scope, domain_id)
        except Exception as exc:
            _LOG.warning("topology snapshot failed", extra={"error_type": type(exc).__name__})
            return expand_model_nodes(payload, None)
        return expand_model_nodes(payload, snapshot.model_ids)

    async def _deliver(self, session: Session, domain_id: str, *, force: bool) -> None:
        async with session.deliver_lock:
            sub = session.subscriptions.get(domain_id)
            if sub is None:
                return
            await self._refresh_scope(session)
            # Send-time filter: the CURRENT scope decides, not the one at subscribe time.
            if not self._may_read(session, domain_id):
                del session.subscriptions[domain_id]
                self._forget_topology(domain_id)
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
                payload = await self._with_deployment_ids(session, domain_id, payload)
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
