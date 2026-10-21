"""Open sessions on this replica, and the revocation fan-out hook (PRP-18 item 1).

:class:`GatewayRegistry` implements ``neurosphere_core.auth.revocation.PushSessionRegistry``:
register it with ``RevocationHookRegistry.register_push_registry`` and a revocation closes this
replica's sockets for the principal at once (close code 4403). Other replicas learn of a
revocation by the per-session scope refresh (see ``gateway``), within the revocation TTL.

Everything here is bounded: sessions per principal are capped, subscriptions per session are
capped by the gateway, and the counters are plain integers.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Final

from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.scope import IdentityScope

from neurosphere_api.realtime.budgets import TokenBucket

__all__ = [
    "CLOSE_FORBIDDEN",
    "CLOSE_RATE_LIMITED",
    "CLOSE_TRY_LATER",
    "CLOSE_UNAUTHENTICATED",
    "GatewayCounters",
    "GatewayRegistry",
    "Session",
    "Subscription",
]

#: Wire-contract close codes (PRP-18): unauthenticated, forbidden or revoked, budget exceeded.
CLOSE_UNAUTHENTICATED: Final = 4401
CLOSE_FORBIDDEN: Final = 4403
CLOSE_RATE_LIMITED: Final = 4429
#: Standard "try again later": the gateway failed closed on an infrastructure error.
CLOSE_TRY_LATER: Final = 1013


@dataclass(slots=True)
class GatewayCounters:
    """Monotonic counters for this replica (exposed for tests and later metrics wiring)."""

    sessions_opened: int = 0
    revocation_closes: int = 0
    rate_limited: int = 0
    dropped_deltas: int = 0
    deltas_sent: int = 0
    scope_denied_deltas: int = 0


@dataclass(slots=True)
class Subscription:
    digest: str | None = None
    last_sent_at: float | None = None
    failing: bool = False


@dataclass(slots=True)
class Session:
    principal_id: str
    claims: VerifiedClaims
    scope: IdentityScope
    scope_at: float
    bucket: TokenBucket
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    subscriptions: dict[str, Subscription] = field(default_factory=dict)
    seq: int = 0
    violations: int = 0
    close_code: int | None = None
    close_reason: str = ""
    disconnected: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    deliver_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def request_close(self, code: int, reason: str) -> None:
        """First request wins; the connection handler performs the actual close."""
        if self.close_code is None and not self.disconnected:
            self.close_code = code
            self.close_reason = reason
        self.finished.set()

    def mark_disconnected(self) -> None:
        self.disconnected = True
        self.finished.set()


class GatewayRegistry:
    """Implements ``PushSessionRegistry`` for the WebSocket gateway."""

    def __init__(self, *, max_sessions_per_principal: int = 5) -> None:
        if max_sessions_per_principal < 1:
            raise ValueError("max_sessions_per_principal must be at least 1")
        self._max_per_principal = max_sessions_per_principal
        self._by_principal: dict[str, dict[str, Session]] = {}
        self.counters = GatewayCounters()

    def add(self, session: Session) -> bool:
        """Register ``session``; False (not registered) when the principal is at its cap."""
        sessions = self._by_principal.setdefault(session.principal_id, {})
        if len(sessions) >= self._max_per_principal:
            if not sessions:
                del self._by_principal[session.principal_id]
            return False
        sessions[session.id] = session
        self.counters.sessions_opened += 1
        return True

    def remove(self, session: Session) -> None:
        sessions = self._by_principal.get(session.principal_id)
        if sessions is None:
            return
        sessions.pop(session.id, None)
        if not sessions:
            del self._by_principal[session.principal_id]

    @property
    def session_count(self) -> int:
        return sum(len(s) for s in self._by_principal.values())

    def sessions_for(self, principal_id: str) -> tuple[Session, ...]:
        return tuple(self._by_principal.get(principal_id, {}).values())

    async def close_for_principal(self, principal_id: str) -> int:
        """Close every open session of ``principal_id`` on this replica (code 4403)."""
        sessions = self.sessions_for(principal_id)
        for session in sessions:
            session.request_close(CLOSE_FORBIDDEN, "revoked")
        self.counters.revocation_closes += len(sessions)
        return len(sessions)
