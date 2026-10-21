"""Composition of the realtime gateway (PRP-18 item 1): what ``configure_realtime`` installs.

``app.state.realtime`` holds a :class:`RealtimeState`. Authentication and scope derivation reuse
the PRP-06 collaborators already on ``app.state.authz`` (``configure_authz``); this module adds
nothing to ``authz/``. Until BOTH are configured every connection is accepted only to be closed
at once with 1013 (fail closed): an unwired deployment never serves a delta.

No ``from __future__ import annotations``: FastAPI inspects the signatures that use these types.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.revocation import load_revocation_settings
from neurosphere_core.errors import InvalidSchemaError

from neurosphere_api.realtime.registry import GatewayRegistry
from neurosphere_api.realtime.settings import RealtimeSettings
from neurosphere_api.realtime.source import AggregateDeltaSource, DeltaSource

__all__ = ["STATE_ATTRIBUTE", "Clock", "RealtimeState", "Sleeper", "configure_realtime"]

STATE_ATTRIBUTE: Final = "realtime"

#: Epoch seconds. One clock drives rate limits, scope-refresh age and delta timestamps, so a
#: test that fakes it fakes all three.
Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RealtimeState:
    source: DeltaSource
    registry: GatewayRegistry
    settings: RealtimeSettings
    refresh_seconds: float
    clock: Clock
    sleeper: Sleeper


def configure_realtime(
    app: FastAPI,
    *,
    aggregate_reader: AggregateReader | None = None,
    source: DeltaSource | None = None,
    settings: RealtimeSettings | None = None,
    registry: GatewayRegistry | None = None,
    revocation_ttl_seconds: float | None = None,
    clock: Clock = time.time,
    sleeper: Sleeper = asyncio.sleep,
) -> GatewayRegistry:
    """Install the gateway on ``app.state.realtime`` and return its session registry.

    Pass exactly one of ``aggregate_reader`` (the default polling source) or ``source``. The
    returned registry is the object to hand to
    ``RevocationHookRegistry.register_push_registry("websocket", registry)``.
    ``revocation_ttl_seconds`` defaults to ``NS_REVOCATION_TTL_SECONDS`` and bounds the scope
    refresh period (half the TTL), which is how other replicas' revocations reach this one.
    """
    if (aggregate_reader is None) == (source is None):
        raise InvalidSchemaError("pass exactly one of aggregate_reader or source", reason="config")
    cfg = settings if settings is not None else RealtimeSettings()
    ttl = (
        float(revocation_ttl_seconds)
        if revocation_ttl_seconds is not None
        else float(load_revocation_settings().ttl_seconds)
    )
    if not ttl > 0:
        raise InvalidSchemaError("revocation ttl must be positive", reason="config")
    if source is None and aggregate_reader is not None:
        source = AggregateDeltaSource(aggregate_reader, cfg, clock=clock)
    if source is None:
        raise InvalidSchemaError("no delta source", reason="config")
    session_registry = registry or GatewayRegistry(
        max_sessions_per_principal=cfg.max_sessions_per_principal
    )
    state = RealtimeState(
        source=source,
        registry=session_registry,
        settings=cfg,
        refresh_seconds=cfg.effective_refresh_seconds(ttl),
        clock=clock,
        sleeper=sleeper,
    )
    setattr(app.state, STATE_ATTRIBUTE, state)
    return session_registry
