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
``gateway_plane``          optional; its ``store`` (a ``GatewayModeLookup``) answers the
                           observe-mode check of APIM gateway intents (PRP-34 item 2)
=========================  ================================================================

Connector resolution (:meth:`ActionPlane.connector_for`) follows the one core table
(``ACTION_CONNECTORS`` refined by target kind). When the APIM gateway connector is a candidate,
the API gets a planning-only view of it: ``dry_run`` picks the connector by the request's target
kind and, for every APIM kind except ``gateway_mode_change`` itself, first requires the gateway
to be in manage mode (``capability_unavailable`` reason ``gateway_observe_mode``; fails closed
when the gateway registry is not configured). The view never applies, verifies or rolls back.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from fastapi import FastAPI, Request
from neurosphere_connector.write import DryRunResult, WriteConnector, WriteRequest
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest
from neurosphere_core.actions import (
    ActionService,
    ExecutionControl,
    IntentStore,
    PermissionRechecker,
)
from neurosphere_core.actions.targets import (
    APIM_GATEWAY_CONNECTOR,
    WriteTargetSource,
    connector_name_for,
    resolve_write_targets,
)
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.gateway import GatewayModeLookup
from neurosphere_core.gateway.mode import MODE_CHANGE_KIND, require_manage
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.hitl import HitlService, ReviewPolicyRegistry

from neurosphere_api.actions.settings import ActionApiSettings

__all__ = [
    "GATEWAY_PLANE_STATE",
    "ActionPlane",
    "Clock",
    "configure_action_plane",
    "get_action_plane",
]

Clock = Callable[[], datetime]

_UNCONFIGURED: Final = "action_plane_unconfigured"
#: ``app.state`` key of the gateway registry plane (same value as ``neurosphere_api.gateway``).
GATEWAY_PLANE_STATE: Final = "gateway_plane"
_GATEWAY_ID: Final = re.compile(GATEWAY_ID_PATTERN)
_API_NEVER_EXECUTES: Final = "api_never_executes"


def _never_executes() -> CapabilityUnavailableError:
    return CapabilityUnavailableError(
        _API_NEVER_EXECUTES, "the API only plans; the executor worker changes targets"
    )


def _gateway_id(connector: object, canonical_id: str) -> str:
    """The gateway an APIM connector is bound to (or the one a gateway target names)."""
    bound = getattr(getattr(connector, "gateway", None), "gateway_id", None)
    if isinstance(bound, str) and _GATEWAY_ID.fullmatch(bound):
        return bound
    tail = canonical_id.rsplit(":", 1)[-1]
    if _GATEWAY_ID.fullmatch(tail):
        return tail
    raise CapabilityUnavailableError("gateway_unresolved", "the target gateway is not known")


class _PlanningConnector:
    """API-side view over the connectors that may execute one action kind: ``dry_run`` only.

    Picks the connector by the request's target kind (``connector_name_for``) and enforces the
    observe-mode refusal before an APIM plan. ``apply``/``verify``/``rollback`` refuse: only the
    executor worker changes a target (PRP-17 D5).
    """

    def __init__(
        self,
        action_kind: str,
        connectors: dict[str, WriteConnector],
        modes: GatewayModeLookup | None,
    ) -> None:
        self._kind = action_kind
        self._connectors = connectors
        self._modes = modes
        default_name = connector_name_for(action_kind)
        if default_name is None or default_name not in connectors:
            default_name = sorted(connectors)[0]
        self._default = connectors[default_name]

    @property
    def manifest(self) -> ConnectorManifest:
        return self._default.manifest

    @property
    def advisory(self) -> bool:
        return False

    async def _require_manage(self, connector: WriteConnector, request: WriteRequest) -> None:
        if self._modes is None:
            raise DependencyTransientError(
                "gateway registry is not configured", reason="gateway_plane_unconfigured"
            )
        canonical_id = request.target.canonical_id
        await require_manage(
            self._modes, canonical_id.split(":", 2)[1], _gateway_id(connector, canonical_id)
        )

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        name = connector_name_for(self._kind, request.target.entity_type)
        connector = None if name is None else self._connectors.get(name)
        if name is None or connector is None:
            raise CapabilityUnavailableError(
                "write_connector_unsupported_target",
                "no write connector is registered for this target kind",
            )
        if name == APIM_GATEWAY_CONNECTOR and self._kind != MODE_CHANGE_KIND:
            await self._require_manage(connector, request)
        return await connector.dry_run(request)

    # The write path is refused outright (NoReturn satisfies the WriteConnector signatures
    # without this module naming the apply-path result types).
    async def apply(self, request: WriteRequest) -> NoReturn:
        raise _never_executes()

    async def verify(self, request: WriteRequest) -> NoReturn:
        raise _never_executes()

    async def rollback(self, applied: object) -> NoReturn:
        raise _never_executes()


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
    gateway_modes: GatewayModeLookup | None = None

    def now(self) -> datetime:
        at = self.clock()
        if at.tzinfo is None:
            raise DependencyTransientError(
                "action clock is not timezone-aware", reason=_UNCONFIGURED
            )
        return at.astimezone(UTC)

    def connector_for(self, action_kind: str) -> WriteConnector | None:
        """The write connector for ``action_kind``; ``None`` means the intent is advisory.

        A single non-APIM candidate is returned as is. When the APIM gateway connector is a
        candidate, or several connectors share the kind (``model_deployment_swap`` on Foundry
        and on an ``apim_backend``), a planning-only view routes ``dry_run`` by target kind and
        refuses plans against a gateway in observe mode (``gateway_observe_mode``).
        """
        connectors = resolve_write_targets(self.write_targets, action_kind)
        if not connectors:
            return None
        if len(connectors) == 1 and APIM_GATEWAY_CONNECTOR not in connectors:
            return next(iter(connectors.values()))
        return _PlanningConnector(action_kind, connectors, self.gateway_modes)

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
        gateway_modes=_gateway_modes(state),
    )


def _gateway_modes(state: Any) -> GatewayModeLookup | None:
    """The gateway registry store when one is configured (read by duck type: no import of the
    gateway API package, which itself drafts through this plane)."""
    store = getattr(getattr(state, GATEWAY_PLANE_STATE, None), "store", None)
    return store if isinstance(store, GatewayModeLookup) else None


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
