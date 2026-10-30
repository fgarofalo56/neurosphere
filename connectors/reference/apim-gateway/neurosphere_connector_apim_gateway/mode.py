"""``gateway_mode_change``: the audited observe/manage switch of one gateway (PRP-34 item 2).

The executor runs this like any other write: ``dry_run`` (refusals plus, for ``manage``, the
permissions preflight), audit before, ``apply`` (preflight again, then the ETag-conditional flip of
the registration), ``verify`` (read the registration back), audit after; ``rollback`` restores
the prior mode. Nothing is written to the gateway itself: switching to ``observe`` leaves every
published resource serving. The decisions live in ``neurosphere_core.gateway.mode``; this module
adapts them to the ``WriteConnector`` calls and reads the permissions through ARM (GET only).

Target: entity type ``apim_gateway_mode``, canonical id ending in the gateway id,
``target_version`` from ``mode_target_version`` (it moves only when the mode moves).
"""

from __future__ import annotations

from typing import Final

from neurosphere_connector.write import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    build_verify_result,
)
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from neurosphere_core.gateway.mode import (
    GATEWAY_PREFLIGHT_FAILED,
    MODE_TARGET_TYPE,
    GatewayModeSwitch,
    ModeChange,
    evaluate_permissions,
    gateway_id_of_target,
    mode_target_version,
    parse_mode_change,
)
from neurosphere_core.gateway.models import GatewayMode, ModePreflight

from neurosphere_connector_apim_gateway.arm import ApimPermissionsReader
from neurosphere_connector_apim_gateway.gateway import GatewayRef

__all__ = ["MODE_TARGET_TYPE", "GatewayModeHandler"]

_ROLLBACK_REF_PREFIX: Final = "mode:"


def _not_granted(preflight: ModePreflight) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(
        GATEWAY_PREFLIGHT_FAILED, "write access is not granted: " + ", ".join(preflight.missing)
    )


class GatewayModeHandler:
    """Mode switch for the gateway the connector is bound to."""

    def __init__(
        self,
        gateway: GatewayRef,
        permissions: ApimPermissionsReader,
        switch: GatewayModeSwitch,
    ) -> None:
        if switch.gateway_id != gateway.gateway_id:
            raise ValueError("the mode switch is bound to another gateway")
        self.gateway = gateway
        self._permissions = permissions
        self._switch = switch

    # -- helpers ---------------------------------------------------------------------------

    def _change(self, request: WriteRequest) -> ModeChange:
        target = request.target
        if target.entity_type != MODE_TARGET_TYPE:
            raise InvalidSchemaError("not a gateway mode change", reason="wrong_entity")
        cloud = target.canonical_id.split(":", 1)[0]
        if cloud != self.gateway.cloud.value:
            raise InvalidSchemaError("target cloud differs from connector", reason="cloud_mismatch")
        if gateway_id_of_target(target.canonical_id) != self.gateway.gateway_id:
            raise InvalidSchemaError("target is not this gateway", reason="wrong_entity")
        return parse_mode_change(
            [
                {"op": op.op, "path": op.path, "value": op.value}
                for op in request.proposed_diff.operations
            ]
        )

    async def preflight(self) -> ModePreflight:
        """Effective permissions of the service identity at the gateway scope (one GET)."""
        entries = await self._permissions.permissions()
        return evaluate_permissions(entries, now=self._switch.now())

    async def require_manage(self) -> None:
        """Observe-mode guard for resource plans (``gateway_observe_mode``)."""
        await self._switch.require_manage()

    # -- WriteConnector calls --------------------------------------------------------------

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        change = self._change(request)
        await self._switch.check(request.target_version, change)
        if change.desired == "manage":
            preflight = await self.preflight()
            if not preflight.passed:
                raise _not_granted(preflight)
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=True,
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        change = self._change(request)
        current = await self._switch.check(request.target_version, change)
        preflight = await self.preflight() if change.desired == "manage" else None
        if preflight is not None and not preflight.passed:
            raise _not_granted(preflight)
        saved = await self._switch.switch(request.target_version, change, preflight)
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=mode_target_version(saved),
            applied_diff=request.proposed_diff,
            rollback_token=f"{_ROLLBACK_REF_PREFIX}{current.mode}:{saved.mode_revision}",
        )

    async def verify(self, request: WriteRequest) -> VerifyResult:
        self._change(request)
        registration = await self._switch.load()
        observed = {"mode": registration.mode, "mode_changed_by": registration.mode_changed_by}
        return build_verify_result(
            request, observed, observed_version=mode_target_version(registration)
        )

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        prior, revision = _parse_token(applied.rollback_token)
        change = parse_mode_change(
            [
                {"op": op.op, "path": op.path, "value": op.value}
                for op in applied.applied_diff.operations
            ]
        )
        preflight = await self.preflight() if prior == "manage" else None
        restored = await self._switch.restore(
            prior, revision=revision, changed_by=change.changed_by, preflight=preflight
        )
        if restored is None:
            # A later switch superseded this one; putting the old mode back would undo it.
            return RollbackResult(target=applied.target, status="not_needed")
        return RollbackResult(
            target=applied.target,
            status="rolled_back",
            version_after=mode_target_version(restored),
        )


def _parse_token(token: str | None) -> tuple[GatewayMode, int]:
    if token is None or not token.startswith(_ROLLBACK_REF_PREFIX):
        raise InvalidSchemaError("rollback token is not usable", reason="bad_rollback_token")
    prior, _, revision = token[len(_ROLLBACK_REF_PREFIX) :].partition(":")
    if prior not in ("observe", "manage") or not revision.isdigit():
        raise InvalidSchemaError("rollback token is not usable", reason="bad_rollback_token")
    return ("manage" if prior == "manage" else "observe"), int(revision)
