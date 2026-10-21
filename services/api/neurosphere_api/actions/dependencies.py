"""Composition of the action plane for the API (PRP-17 item 4).

Every collaborator comes from ``app.state``; :func:`configure_action_plane` sets them all in one
call (PRP-17 item 7 wires it). Required keys fail closed with 503 (``dependency_transient``,
reason ``action_plane_unconfigured``) when absent or of the wrong type:

=========================  ================================================================
``app.state`` key          Type
=========================  ================================================================
``action_service``         ``neurosphere_core.actions.ActionService`` (the ONLY state writer)
``intent_store``           ``neurosphere_core.actions.IntentStore`` (read: list intents)
``hitl_service``           ``neurosphere_core.hitl.HitlService``
``review_policies``        ``neurosphere_core.hitl.ReviewPolicyRegistry`` (same as the HITL one)
``write_targets``          ``WriteTargetSource`` (a ``neurosphere_connector.write.
                           WriteTargetRegistry``); only ``dry_run`` is ever called from here
``permission_rechecker``   ``neurosphere_core.actions.PermissionRechecker`` (validation checks)
``execution_control``      ``neurosphere_core.actions.ExecutionControl`` (kill switch)
``audit_repository``       ``neurosphere_core.audit.AuditRepository`` (kill-switch changes)
``action_api_settings``    optional ``ActionApiSettings`` (defaults when unset)
``action_clock``           optional ``() -> datetime`` (aware; default UTC now)
``reviewer_directory``     optional ``ReviewerDirectory`` (assigning another reviewer)
=========================  ================================================================

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast

from fastapi import FastAPI, Request
from neurosphere_connector.write import WriteConnector
from neurosphere_core.actions import (
    ActionService,
    ExecutionControl,
    IntentStore,
    PermissionRechecker,
)
from neurosphere_core.actions.targets import WriteTargetSource, resolve_write_target
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.hitl import HitlService, ReviewPolicyRegistry

from neurosphere_api.actions.settings import ActionApiSettings

__all__ = [
    "ActionPlane",
    "Clock",
    "configure_action_plane",
    "get_action_plane",
]

Clock = Callable[[], datetime]

_UNCONFIGURED: Final = "action_plane_unconfigured"
_REQUIRED: Final[dict[str, type]] = {
    "action_service": ActionService,
    "intent_store": IntentStore,
    "hitl_service": HitlService,
    "review_policies": ReviewPolicyRegistry,
    "write_targets": WriteTargetSource,
    "permission_rechecker": PermissionRechecker,
    "execution_control": ExecutionControl,
    "audit_repository": AuditRepository,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ActionPlane:
    """Everything one action or review request needs, read from ``app.state``."""

    actions: ActionService
    intents: IntentStore
    hitl: HitlService
    policies: ReviewPolicyRegistry
    write_targets: WriteTargetSource[WriteConnector]
    rechecker: PermissionRechecker
    control: ExecutionControl
    audit: AuditRepository
    settings: ActionApiSettings
    clock: Clock
    reviewer_directory: object | None = None

    def now(self) -> datetime:
        at = self.clock()
        if at.tzinfo is None:
            raise DependencyTransientError(
                "action clock is not timezone-aware", reason=_UNCONFIGURED
            )
        return at.astimezone(UTC)

    def connector_for(self, action_kind: str) -> WriteConnector | None:
        """The write connector for ``action_kind``; ``None`` means the intent is advisory."""
        return resolve_write_target(self.write_targets, action_kind)

    def requires_approval(self, action_kind: str) -> bool:
        return self.settings.requires_approval(action_kind)

    def self_approval_forbidden(self, action_kind: str) -> bool:
        """Maker-checker policy for ``action_kind``; unresolvable forbids (fail closed)."""
        try:
            return self.policies.resolve("maker_checker", action_kind).self_approval_forbidden
        except Exception:
            return True


def get_action_plane(request: Request) -> ActionPlane:
    state = request.app.state
    found: dict[str, Any] = {}
    for key, kind in _REQUIRED.items():
        value = getattr(state, key, None)
        if value is None or not isinstance(value, kind):
            raise DependencyTransientError("action plane is not configured", reason=_UNCONFIGURED)
        found[key] = value
    settings = getattr(state, "action_api_settings", None)
    if settings is None:
        settings = ActionApiSettings()
    elif not isinstance(settings, ActionApiSettings):
        raise DependencyTransientError("action plane is not configured", reason=_UNCONFIGURED)
    clock = getattr(state, "action_clock", None) or _utc_now
    return ActionPlane(
        actions=found["action_service"],
        intents=found["intent_store"],
        hitl=found["hitl_service"],
        policies=found["review_policies"],
        write_targets=cast(WriteTargetSource[WriteConnector], found["write_targets"]),
        rechecker=found["permission_rechecker"],
        control=found["execution_control"],
        audit=found["audit_repository"],
        settings=settings,
        clock=clock,
        reviewer_directory=getattr(state, "reviewer_directory", None),
    )


def configure_action_plane(
    app: FastAPI,
    *,
    action_service: ActionService,
    intent_store: IntentStore,
    hitl_service: HitlService,
    review_policies: ReviewPolicyRegistry,
    write_targets: WriteTargetSource[WriteConnector],
    permission_rechecker: PermissionRechecker,
    execution_control: ExecutionControl,
    audit_repository: AuditRepository,
    settings: ActionApiSettings | None = None,
    clock: Clock | None = None,
    reviewer_directory: object | None = None,
) -> None:
    """Install every action-plane collaborator on ``app.state`` (one call for item 7)."""
    state = app.state
    state.action_service = action_service
    state.intent_store = intent_store
    state.hitl_service = hitl_service
    state.review_policies = review_policies
    state.write_targets = write_targets
    state.permission_rechecker = permission_rechecker
    state.execution_control = execution_control
    state.audit_repository = audit_repository
    state.action_api_settings = settings or ActionApiSettings()
    state.action_clock = clock
    state.reviewer_directory = reviewer_directory
