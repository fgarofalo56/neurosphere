"""Realtime WebSocket gateway (PRP-18 item 1): scoped deltas from hot aggregates.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/realtime``, WebSocket route ``/ws``) for
  ``RouterRegistry``. Not added to ``routers.py`` here; PRP-18 item 7 owns that wiring.
* :func:`configure_realtime` -- installs the gateway on ``app.state.realtime`` and returns the
  :class:`GatewayRegistry`. Requires ``configure_authz`` (token validator and scope deriver);
  without either, every connection is closed at once with 1013 (fail closed).
* :class:`GatewayRegistry` -- implements ``PushSessionRegistry``; item 7 passes it to
  ``RevocationHookRegistry.register_push_registry("websocket", registry)``.
* :class:`DeltaSource` / :class:`AggregateDeltaSource` -- where deltas come from (the PRP-14
  ``AggregateReader``; never raw events or the ledger).
* :class:`RealtimeSettings` -- ``NS_REALTIME_*`` budgets and intervals.

Auth: ``Sec-WebSocket-Protocol: ns.bearer, <token>`` (browsers) or an ``Authorization`` header.
Close codes: 4401 unauthenticated, 4403 forbidden or revoked, 4429 budget exceeded, 1013 the
gateway failed closed on an infrastructure error. See :mod:`neurosphere_api.realtime.gateway`.
"""

from neurosphere_api.realtime.dependencies import (
    RealtimeState,
    configure_realtime,
)
from neurosphere_api.realtime.registry import (
    CLOSE_FORBIDDEN,
    CLOSE_RATE_LIMITED,
    CLOSE_TRY_LATER,
    CLOSE_UNAUTHENTICATED,
    GatewayCounters,
    GatewayRegistry,
)
from neurosphere_api.realtime.router import PREFIX, build_router, register
from neurosphere_api.realtime.settings import RealtimeSettings
from neurosphere_api.realtime.source import (
    AggregateDeltaSource,
    Coverage,
    DeltaPayload,
    DeltaSource,
)

__all__ = [
    "CLOSE_FORBIDDEN",
    "CLOSE_RATE_LIMITED",
    "CLOSE_TRY_LATER",
    "CLOSE_UNAUTHENTICATED",
    "PREFIX",
    "AggregateDeltaSource",
    "Coverage",
    "DeltaPayload",
    "DeltaSource",
    "GatewayCounters",
    "GatewayRegistry",
    "RealtimeSettings",
    "RealtimeState",
    "build_router",
    "configure_realtime",
    "register",
]
