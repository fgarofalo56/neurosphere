"""Canary phase of the executor (PRP-17 delta D4).

The PRP-09 ``WriteConnector`` has no canary method and the documented Foundry deployment PUT has
no traffic split, so the canary is an EXECUTOR phase between apply and the final verify. A
:class:`CanaryProbe` gets the request, the connector's :class:`ApplyResult` and a first read-back
(:class:`VerifyResult`) of the target, and answers ``passed``, ``failed`` or ``verify_only``.
``failed`` (or a probe that raises, or answers anything else) rolls the change back.

:class:`VerifyOnlyCanary` is the default: it runs no probe of its own and records
``canary="verify_only"`` so evidence never claims a traffic canary that did not happen.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from neurosphere_connector.write import ApplyResult, VerifyResult, WriteRequest
from neurosphere_core.actions import CanaryOutcome

__all__ = ["CANARY_OUTCOMES", "CanaryProbe", "VerifyOnlyCanary"]

CANARY_OUTCOMES: Final[frozenset[str]] = frozenset({"passed", "failed", "verify_only"})


@runtime_checkable
class CanaryProbe(Protocol):
    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        """Judge the applied change; ``failed`` triggers a rollback."""
        ...


class VerifyOnlyCanary:
    """No traffic-split canary exists for the target: record ``verify_only`` honestly."""

    async def probe(
        self, request: WriteRequest, applied: ApplyResult, observed: VerifyResult
    ) -> CanaryOutcome:
        return "verify_only"
