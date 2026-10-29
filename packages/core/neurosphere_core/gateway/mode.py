"""Observe/manage mode of a registered gateway (PRP-34 item 2).

A registration starts, and a reused enterprise APIM stays, in ``observe``. The only way to
``manage`` is a ``gateway_mode_change`` action intent (maker-checker per policy) whose connector
step proves write access first: the ``Microsoft.Authorization/permissions`` list at the gateway
scope must grant every action in :data:`REQUIRED_WRITE_ACTIONS` to the service identity. The
flip itself is an ETag-conditional replace of the registration (:class:`GatewayModeSwitch`).

What this module decides (connector- and API-agnostic; core never imports a connector):

* the mode-change intent shape: target ``apim_gateway_mode``, ``target_version`` bound to the
  registration's ``mode_revision`` and mode, a two-operation ``replace`` diff;
* the permissions evaluation (Azure RBAC wildcard semantics, ``notActions`` per entry);
* the Government refusal (APIM v2 tiers ``unverified`` in the capability matrix);
* the refusals: unchanged mode, a gateway that is busy applying, a failed preflight;
* :func:`require_manage`, the observe-mode guard every plan/apply path asks first
  (``capability_unavailable`` reason ``gateway_observe_mode``).

Switching back to ``observe`` writes nothing to the gateway: published resources keep serving,
and only NeuroSphere's further plans, applies and unpublishes are refused.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol, cast, get_args, runtime_checkable

from neurosphere_core.capabilities.validate import default_matrix
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
    ValidationIssue,
)
from neurosphere_core.gateway.models import (
    GATEWAY_ID_PATTERN,
    GatewayMode,
    GatewayRegistration,
    ModePreflight,
)
from neurosphere_core.gateway.store import GatewayModeLookup, GatewayStore

__all__ = [
    "GATEWAY_APPLYING",
    "GATEWAY_MANAGE_UNAVAILABLE",
    "GATEWAY_NOT_REGISTERED",
    "GATEWAY_OBSERVE_MODE",
    "GATEWAY_PREFLIGHT_FAILED",
    "GOVERNMENT_MANAGE_ROW",
    "MODE_CHANGE_KIND",
    "MODE_TARGET_TYPE",
    "MODE_UNCHANGED",
    "PERMISSIONS_API_VERSION",
    "REQUIRED_WRITE_ACTIONS",
    "ActivityProbe",
    "GatewayModeSwitch",
    "ModeChange",
    "evaluate_permissions",
    "gateway_id_of_target",
    "manage_refusal",
    "mode_change_diff",
    "mode_target",
    "mode_target_version",
    "parse_mode_change",
    "require_manage",
]

MODE_CHANGE_KIND: Final = "gateway_mode_change"
#: Target entity type of a mode change; the canonical id names the gateway itself.
MODE_TARGET_TYPE: Final = "apim_gateway_mode"
GATEWAY_OBSERVE_MODE: Final = "gateway_observe_mode"
GATEWAY_MANAGE_UNAVAILABLE: Final = "gateway_manage_unavailable"
GATEWAY_APPLYING: Final = "gateway_applying"
GATEWAY_PREFLIGHT_FAILED: Final = "gateway_preflight_failed"
GATEWAY_NOT_REGISTERED: Final = "gateway_not_registered"
MODE_UNCHANGED: Final = "gateway_mode_unchanged"
#: Same row the connector's Government refusal reads: v2 tiers are unverified in Government, so
#: manage stays disabled there until this row says ``available``.
GOVERNMENT_MANAGE_ROW: Final = "apim.backend_pool.government.any.standard_v2"
#: ``Microsoft.Authorization/permissions`` list API version (Permissions - List For Resource).
PERMISSIONS_API_VERSION: Final = "2022-04-01"

_APIM: Final = "Microsoft.ApiManagement/service"
_CHILD_KINDS: Final = (
    "namedValues",
    "backends",
    "policyFragments",
    "apis",
    "apis/operations",
    "apis/policies",
    "products",
    "products/policies",
    "products/apiLinks",
    "subscriptions",
)
#: The service write plus write and delete of every child kind the connector plans (rollback
#: deletes what a run created, so delete is required too).
REQUIRED_WRITE_ACTIONS: Final[tuple[str, ...]] = (
    f"{_APIM}/write",
    *(f"{_APIM}/{kind}/write" for kind in _CHILD_KINDS),
    *(f"{_APIM}/{kind}/delete" for kind in _CHILD_KINDS),
)
_MODES: Final = frozenset(get_args(GatewayMode))
_GATEWAY_ID: Final = re.compile(GATEWAY_ID_PATTERN)
_MODE_PATH: Final = "/mode"
_BY_PATH: Final = "/mode_changed_by"
_RUNNING_DETAIL: Final = "a plan, apply, rollback or unpublish is running on this gateway"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


# -- intent shape ---------------------------------------------------------------------------------


def mode_target(registration: GatewayRegistration) -> dict[str, str]:
    """``TargetRef`` fields of a mode change on ``registration``."""
    return {
        "canonical_id": (
            f"{registration.cloud}:{registration.customer_id}:apim:{MODE_TARGET_TYPE}:"
            f"{registration.id}"
        ),
        "entity_type": MODE_TARGET_TYPE,
    }


def mode_target_version(registration: GatewayRegistration) -> str:
    """The version a mode-change intent binds to: it moves only when the mode moves."""
    return f"mode-r{registration.mode_revision}-{registration.mode}"


def mode_change_diff(desired: GatewayMode, changed_by: str) -> list[dict[str, Any]]:
    """The exact change a maker confirms: the new mode and who asked for it (a pseudonym)."""
    return [
        {"op": "replace", "path": _MODE_PATH, "value": desired},
        {"op": "replace", "path": _BY_PATH, "value": changed_by},
    ]


@dataclass(frozen=True)
class ModeChange:
    desired: GatewayMode
    changed_by: str


def _bad_diff(detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        detail,
        errors=[ValidationIssue("/proposed_diff", detail)],
        reason="bad_mode_change",
    )


def parse_mode_change(operations: Sequence[Mapping[str, Any]]) -> ModeChange:
    """Strict inverse of :func:`mode_change_diff` (two ``replace`` operations, any order)."""
    values: dict[str, Any] = {}
    for op in operations:
        path = op.get("path")
        if op.get("op") != "replace" or path not in (_MODE_PATH, _BY_PATH) or path in values:
            raise _bad_diff("a mode change replaces /mode and /mode_changed_by exactly once")
        values[cast(str, path)] = op.get("value")
    desired = values.get(_MODE_PATH)
    changed_by = values.get(_BY_PATH)
    if desired not in _MODES:
        raise _bad_diff("mode must be observe or manage")
    if not isinstance(changed_by, str) or not 1 <= len(changed_by) <= 256:
        raise _bad_diff("mode_changed_by must be the requesting principal's pseudonym")
    return ModeChange(desired=cast(GatewayMode, desired), changed_by=changed_by)


def gateway_id_of_target(canonical_id: str) -> str:
    """The gateway id a mode-change (or ``apim_gateway``) canonical id ends with."""
    gateway_id = canonical_id.rsplit(":", 1)[-1]
    if not _GATEWAY_ID.fullmatch(gateway_id):
        raise InvalidSchemaError("target does not name a gateway", reason="wrong_entity")
    return gateway_id


# -- refusals -------------------------------------------------------------------------------------


def manage_refusal(cloud: str) -> CapabilityUnavailableError | None:
    """Why manage mode is disabled in ``cloud``, or None when it may be enabled."""
    if cloud == "commercial":
        return None
    row = default_matrix().by_id(GOVERNMENT_MANAGE_ROW)
    if row is not None and row.availability == "available":
        return None
    reason = (
        row.notes
        if row is not None and row.notes
        else "APIM v2 tiers are unverified in Azure Government"
    )
    return CapabilityUnavailableError(GATEWAY_MANAGE_UNAVAILABLE, reason)


async def require_manage(
    lookup: GatewayModeLookup, customer_id: str, gateway_id: str
) -> GatewayRegistration:
    """The registration when it is in manage mode; otherwise ``capability_unavailable``.

    Plans, applies and unpublishes against a gateway in observe mode are refused with reason
    ``gateway_observe_mode``; an unknown gateway fails closed.
    """
    registration = await lookup.find(customer_id, gateway_id)
    if registration is None:
        raise CapabilityUnavailableError(
            GATEWAY_NOT_REGISTERED, "the gateway is not registered for this customer"
        )
    if registration.mode != "manage":
        raise CapabilityUnavailableError(
            GATEWAY_OBSERVE_MODE,
            "the gateway is in observe mode; switch it to manage before changing it",
        )
    refusal = manage_refusal(registration.cloud)
    if refusal is not None:
        raise refusal
    return registration


# -- preflight ------------------------------------------------------------------------------------


def _pattern(action: str) -> re.Pattern[str]:
    return re.compile(
        "^" + ".*".join(re.escape(part) for part in action.split("*")) + "$", re.IGNORECASE
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in cast(list[object], value) if isinstance(v, str)]


def _granted(action: str, entries: Sequence[Mapping[str, Any]]) -> bool:
    """Azure RBAC: some entry's ``actions`` match and none of that entry's ``notActions`` do."""
    for entry in entries:
        allowed = any(_pattern(a).match(action) for a in _strings(entry.get("actions")))
        if allowed and not any(
            _pattern(n).match(action) for n in _strings(entry.get("notActions"))
        ):
            return True
    return False


def evaluate_permissions(
    entries: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    required: Sequence[str] = REQUIRED_WRITE_ACTIONS,
) -> ModePreflight:
    """Preflight from a ``Microsoft.Authorization/permissions`` ``value`` list.

    Data actions are ignored (APIM management writes are control-plane actions). The list does
    not reflect deny assignments; a deny makes the first real write fail with ``forbidden`` and
    the applier reverses, so the preflight is necessary, not sufficient.
    """
    missing = [action for action in required if not _granted(action, entries)]
    return ModePreflight(
        passed=not missing, checked_at=now, required=list(required), missing=missing
    )


# -- the switch -----------------------------------------------------------------------------------


@runtime_checkable
class ActivityProbe(Protocol):
    async def running(self, gateway_id: str) -> bool:
        """True while a plan, apply, rollback or unpublish is running on the gateway."""
        ...


class GatewayModeSwitch:
    """Checks and flips the mode of ONE registration (the connector's mode step uses it)."""

    def __init__(
        self,
        store: GatewayStore,
        *,
        customer_id: str,
        domain_id: str,
        gateway_id: str,
        activity: ActivityProbe,
        clock: Clock = _utc_now,
    ) -> None:
        self._store = store
        self._customer_id = customer_id
        self._domain_id = domain_id
        self._gateway_id = gateway_id
        self._activity = activity
        self._clock = clock

    @property
    def gateway_id(self) -> str:
        return self._gateway_id

    def now(self) -> datetime:
        return self._clock().astimezone(UTC)

    async def load(self) -> GatewayRegistration:
        found = await self._store.get(self._customer_id, self._domain_id, self._gateway_id)
        if found is None:
            raise InvalidSchemaError("the gateway is not registered", reason="target_not_found")
        return found

    async def require_manage(self) -> GatewayRegistration:
        """The observe-mode guard for this switch's gateway."""
        found = await self.load()
        return await require_manage(_Fixed(found), self._customer_id, self._gateway_id)

    async def check(self, target_version: str, change: ModeChange) -> GatewayRegistration:
        """Refusals that need no ARM call: version, unchanged, Government, busy."""
        registration = await self.load()
        if mode_target_version(registration) != target_version:
            raise StaleVersionError("the gateway mode changed", reason="target_version_changed")
        if change.desired == registration.mode:
            raise InvalidSchemaError(
                f"the gateway is already in {registration.mode} mode", reason=MODE_UNCHANGED
            )
        if change.desired == "manage":
            refusal = manage_refusal(registration.cloud)
            if refusal is not None:
                raise refusal
        if await self._activity.running(registration.id):
            raise CapabilityUnavailableError(GATEWAY_APPLYING, _RUNNING_DETAIL)
        return registration

    async def switch(
        self, target_version: str, change: ModeChange, preflight: ModePreflight | None
    ) -> GatewayRegistration:
        """Flip the mode (ETag-conditional). Manage needs a passed ``preflight``."""
        registration = await self.check(target_version, change)
        if change.desired == "manage" and (preflight is None or not preflight.passed):
            missing = ", ".join(preflight.missing) if preflight is not None else "not run"
            raise CapabilityUnavailableError(
                GATEWAY_PREFLIGHT_FAILED, f"write access is not granted: {missing}"
            )
        return await self._write(registration, change.desired, change.changed_by, preflight)

    async def restore(
        self, prior: GatewayMode, *, revision: int, changed_by: str, preflight: ModePreflight | None
    ) -> GatewayRegistration | None:
        """Put ``prior`` back after a switch to ``revision``; None when it moved on since.

        Restoring ``manage`` needs a fresh passed preflight like any switch to manage.
        """
        registration = await self.load()
        if registration.mode_revision != revision:
            return None
        if registration.mode == prior:
            return registration
        if prior == "manage":
            refusal = manage_refusal(registration.cloud)
            if refusal is not None:
                raise refusal
            if preflight is None or not preflight.passed:
                raise CapabilityUnavailableError(
                    GATEWAY_PREFLIGHT_FAILED, "write access is not granted; manage not restored"
                )
        return await self._write(registration, prior, changed_by, preflight)

    async def _write(
        self,
        registration: GatewayRegistration,
        mode: GatewayMode,
        changed_by: str,
        preflight: ModePreflight | None,
    ) -> GatewayRegistration:
        at = self.now()
        data = registration.model_dump()
        data.update(
            mode=mode,
            mode_changed_by=changed_by,
            mode_changed_at=at,
            mode_revision=registration.mode_revision + 1,
            # Observe keeps the last preflight for display; manage stores the one that passed.
            preflight=preflight if preflight is not None else registration.preflight,
            updated_at=at,
        )
        # model_validate (not model_copy) so the manage invariant is enforced on the way out.
        updated = GatewayRegistration.model_validate(data)
        return await self._store.replace(updated, if_match=registration.etag or "")


class _Fixed:
    """A :class:`GatewayModeLookup` over one already-loaded registration."""

    def __init__(self, registration: GatewayRegistration) -> None:
        self._registration = registration

    async def find(self, customer_id: str, gateway_id: str) -> GatewayRegistration | None:
        found = self._registration
        if found.customer_id == customer_id and found.id == gateway_id:
            return found
        return None
