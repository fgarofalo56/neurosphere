"""The governance policy plane on ``app.state`` and its FastAPI dependency (PRP-105 item 6).

:class:`GovernancePolicyPlane` is what ``runtime/builders/governance.py`` installs as
``app.state.governance_policy``: the engine stores, the lifecycle, the decider, the rule registry
(built through ``RuleEvaluatorRegistry.discover``, so the API refuses exactly the kinds the worker
cannot evaluate) and the exception requester. Nothing in the plane writes a published state on
a request: publish and retire are drafted as action intents (``service.py``).

When the component is off (``NS_GOVPOLICY_ENABLED=false``) or could not be built, the attribute
is ``None`` and every route answers 503 ``dependency_transient`` reason ``capability_unavailable``;
``app.state.governance_policy_off_reason`` carries the reason code (logged, never a value).

No ``from __future__ import annotations``: FastAPI inspects the dependency signature.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import Depends, FastAPI, Request
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.governance.policy import (
    BindingStore,
    EvaluationStatusStore,
    ExceptionRequester,
    ExceptionStore,
    PolicyDecider,
    PolicyDefinitionStore,
    PolicyLifecycle,
    ViolationStore,
)
from neurosphere_core.governance.policy.rules import RuleEvaluatorRegistry

__all__ = [
    "CAPABILITY_UNAVAILABLE",
    "OFF_REASON_ATTRIBUTE",
    "STATE_ATTRIBUTE",
    "GovernancePolicyPlane",
    "Plane",
    "configure_governance_policy",
    "get_plane",
]

STATE_ATTRIBUTE: Final = "governance_policy"
OFF_REASON_ATTRIBUTE: Final = "governance_policy_off_reason"
CAPABILITY_UNAVAILABLE: Final = "capability_unavailable"

Backend = Literal["cosmos", "memory"]


@dataclass(frozen=True, slots=True)
class GovernancePolicyPlane:
    """Everything the governance policy routes use (``app.state.governance_policy``).

    ``policies``, ``violations``, ``exceptions``, ``bindings`` and ``statuses`` are the PRP-105
    stores (Cosmos, or in-memory under ``NS_ENV=local`` only); ``lifecycle`` is the ONLY code that
    marks a version published or retired (PRP-108's handler and the local seed call it, never a
    route); ``decider`` answers ``decide`` for later enforcement points; ``registry`` holds the
    evaluable rule kinds; ``exception_requester`` opens HITL ``policy_exception`` reviews.
    """

    policies: PolicyDefinitionStore
    violations: ViolationStore
    exceptions: ExceptionStore
    bindings: BindingStore
    statuses: EvaluationStatusStore
    lifecycle: PolicyLifecycle
    decider: PolicyDecider
    registry: RuleEvaluatorRegistry
    exception_requester: ExceptionRequester
    audit: AuditRepository
    clock: Callable[[], datetime]
    backend: Backend
    exception_max_days: int


def configure_governance_policy(
    app: FastAPI, plane: GovernancePolicyPlane | None, *, off_reason: str | None = None
) -> None:
    """Install (or clear, with ``None``) the plane and its off reason on ``app.state``."""
    setattr(app.state, STATE_ATTRIBUTE, plane)
    setattr(app.state, OFF_REASON_ATTRIBUTE, None if plane is not None else off_reason)


def get_plane(request: Request) -> GovernancePolicyPlane:
    """The installed plane, else 503 ``capability_unavailable`` (component off or not built)."""
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, GovernancePolicyPlane):
        raise DependencyTransientError(
            "the governance policy engine is not enabled in this deployment",
            reason=CAPABILITY_UNAVAILABLE,
        )
    return plane


Plane = Annotated[GovernancePolicyPlane, Depends(get_plane)]
