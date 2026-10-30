"""Canary probe for model swaps on an APIM backend (PRP-34 item 3; PRP-17 delta D4).

The executor owns the phases (apply -> canary -> verify); this module only plugs a
:class:`~neurosphere_workers.actions.canary.CanaryProbe` into the canary phase. It never writes:
the weight shift itself is the reviewed, applied change (``swap`` module of the APIM connector
caps a member's first raise at the canary share, 10 percent by default).

Per ``apim_backend`` intent:

* ``Single`` backend: the URL swap is atomic, APIM has no traffic split for it, so the outcome
  is ``verify_only`` and the execution record says exactly that.
* ``Pool`` backend: the executor's read-back must have matched, then the probe reads the pool
  back itself and requires every member weight to equal the reviewed document. When the gateway
  writes ``GatewayLogs`` (registration ``diagnostics.gateway_logs`` and a workspace), the probe
  then waits up to ``window`` for ONE ``ApiManagementGatewayLogs`` row whose ``BackendId`` names
  each member the shift raised, through the PRP-33 Azure Monitor gateway observation connector
  (fixed KQL, bounded polling). No row within the window is a canary failure (the executor then
  rolls the shift back). Diagnostics enabled but no log source wired also fails, closed.
* Any other target kind is delegated to ``fallback`` (``verify_only`` by default), so Foundry
  swaps keep their PRP-17 behaviour.

Bounded wait: one query per ``interval`` until ``window`` has passed since the probe started (the
clock and the sleep are injectable). Nothing secret is read or logged: rows are matched on the
backend id only; logs carry the intent-free reason code.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_connector.write import ApplyResult, VerifyResult, WriteRequest
from neurosphere_connector_apim_gateway import ApimArm, GatewayRef
from neurosphere_connector_apim_gateway.swap import (
    BACKEND_ENTITY_TYPE,
    BackendSwapTranslator,
    pool_weights,
)
from neurosphere_connector_azure_monitor import MonitorSource, PollResult, SourceKind
from neurosphere_core.actions import CanaryOutcome
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.gateway.store import GatewayModeLookup

from neurosphere_workers.actions.canary import CanaryProbe, VerifyOnlyCanary

__all__ = [
    "CANARY_LOGS_UNAVAILABLE",
    "DEFAULT_PROBE_INTERVAL",
    "DEFAULT_PROBE_WINDOW",
    "ApimBackendCanaryProbe",
    "GatewayLogSource",
]

logger = logging.getLogger("neurosphere.workers.actions.apim_canary")

DEFAULT_PROBE_WINDOW: Final = timedelta(minutes=5)
DEFAULT_PROBE_INTERVAL: Final = timedelta(seconds=30)
CANARY_LOGS_UNAVAILABLE: Final = "canary_logs_unavailable"

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


@runtime_checkable
class GatewayLogSource(Protocol):
    """What the probe needs from the PRP-33 Azure Monitor connector (a fake in tests)."""

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _backend_name(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.rsplit("/", 1)[-1].lower()


def _seen_backends(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {name for row in rows if (name := _backend_name(row.get("BackendId"))) is not None}


class ApimBackendCanaryProbe:
    """``CanaryProbe`` for one APIM gateway's backend swaps; delegates other targets."""

    def __init__(
        self,
        *,
        gateway: GatewayRef,
        arm: ApimArm,
        gateways: GatewayModeLookup,
        logs: GatewayLogSource | None = None,
        translator: BackendSwapTranslator | None = None,
        window: timedelta = DEFAULT_PROBE_WINDOW,
        interval: timedelta = DEFAULT_PROBE_INTERVAL,
        clock: Clock = _utc_now,
        sleep: Sleep = asyncio.sleep,
        fallback: CanaryProbe | None = None,
    ) -> None:
        if window <= timedelta(0) or interval <= timedelta(0):
            raise ValueError("window and interval must be positive")
        self._gateway = gateway
        self._arm = arm
        self._gateways = gateways
        self._logs = logs
        self._translator = translator or BackendSwapTranslator()
        self._window = window
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._fallback: CanaryProbe = fallback or VerifyOnlyCanary()

    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        if request.target.entity_type != BACKEND_ENTITY_TYPE:
            return await self._fallback.probe(request, applied, observed)
        started = self._clock()
        swap = self._translator.parse(self._gateway, request)
        if swap.kind == "single":
            self._log("apim_single_backend_atomic_swap")
            return "verify_only"
        if not observed.matched:
            self._log("apim_pool_not_observed")
            return "failed"
        current = await self._arm.get(swap.path)
        if current is None or pool_weights(current.properties) != pool_weights(swap.desired):
            self._log("apim_pool_weights_not_read_back")
            return "failed"
        raised = {shift.member.lower() for shift in swap.raised}
        if not raised:
            return "passed"  # read back; no member gained traffic share to watch
        customer_id = request.target.canonical_id.split(":", 2)[1]
        registration = await self._gateways.find(customer_id, self._gateway.gateway_id)
        if registration is None:
            self._log("gateway_not_registered")
            return "failed"
        if not registration.diagnostics.gateway_logs:
            return "passed"  # no GatewayLogs: the pool read-back is the whole canary
        if self._logs is None or registration.workspace_id is None:
            self._log(CANARY_LOGS_UNAVAILABLE)
            return "failed"
        source = MonitorSource(SourceKind.APIM_GATEWAY, registration.workspace_id)
        if await self._rows_seen(source, raised, started):
            return "passed"
        self._log("apim_canary_no_log_row")
        return "failed"

    async def _rows_seen(self, source: MonitorSource, members: set[str], since: datetime) -> bool:
        assert self._logs is not None
        deadline = since + self._window
        while True:
            try:
                result = await self._logs.poll([source], watermark=since)
                if members <= _seen_backends(result.records):
                    return True
            except NeuroSphereError as exc:  # a failed query is retried inside the window
                self._log(exc.code)
            if self._clock() >= deadline:
                return False
            await self._sleep(self._interval.total_seconds())

    @staticmethod
    def _log(reason: str) -> None:
        logger.info("apim canary probe", extra={"event": "action.apim_canary", "reason": reason})
