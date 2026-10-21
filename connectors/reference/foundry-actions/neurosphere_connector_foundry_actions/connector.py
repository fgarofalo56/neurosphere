"""Foundry model-deployment swap: a real write connector plus a separate advisory connector.

Registry rule (PRP-09): advisory connectors cannot back actions, so advisory mode is a different
object. ``create_swap_connector`` returns the write connector only when the Commercial target is
reachable and the credential holds ``Microsoft.CognitiveServices/accounts/deployments/write``
(Permissions - List For Resource); otherwise it returns the advisory connector, which performs
zero writes.

``target_version`` is the deployment's ARM ``etag``. ``If-Match`` on the PUT is not documented,
so it is not relied on: the etag is re-read immediately before the PUT and a difference raises
``stale_version`` (reason ``target_version_changed``). A small window between that GET and the
PUT remains (TOCTOU); see docs/evidence/G05/README.md.

Success evidence is the observed deployment (GET), never catalog metadata. The swap is in place:
the documented PUT has no traffic split, so there is no connector-level canary (PRP-17 D4).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from neurosphere_connector import build_manifest
from neurosphere_connector.write import (
    AdvisoryWriteMixin,
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    build_verify_result,
)
from neurosphere_connector.write.write_models import OperationCheck
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.capabilities.validate import default_matrix
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)

from neurosphere_connector_foundry_actions.arm import ArmClient
from neurosphere_connector_foundry_actions.endpoints import AccountRef, validate_name
from neurosphere_connector_foundry_actions.logic import (
    DEPLOYMENT_WRITE_ACTION,
    TERMINAL_FAILURE_STATES,
    CompatCheck,
    apply_patch,
    build_put_body,
    can_write_deployments,
    model_of,
    run_compatibility,
    verification_diff,
)

__all__ = [
    "ADVISORY_CONNECTOR_NAME",
    "CONNECTOR_NAME",
    "FoundryModelSwapAdvisoryConnector",
    "FoundryModelSwapConnector",
    "create_swap_connector",
]

CONNECTOR_NAME = "foundry-model-swap"
ADVISORY_CONNECTOR_NAME = "foundry-model-swap-advisory"
DOCUMENTATION_URL = "https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments"
_ROW_GOV = "foundry.deployment_write.government.global.any"

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Today = Callable[[], date]


def _today() -> date:
    return datetime.now(UTC).date()


def _manifest(*, advisory: bool) -> ConnectorManifest:
    return build_manifest(
        name=ADVISORY_CONNECTOR_NAME if advisory else CONNECTOR_NAME,
        version="0.1.0",
        capabilities=["health_reporting"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="unknown", subject_level="deployment"),
        scopes=["https://management.azure.com/.default"],
        write_actions=[] if advisory else ["model_deployment_swap"],
        documentation_url=DOCUMENTATION_URL,
    )


def _describe(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    return f"{type(exc).__name__}: {reason}" if reason else type(exc).__name__


def _refuse_cloud(account: AccountRef) -> None:
    """Government is disabled by the capability matrix (G01); never reroute to Commercial."""
    if account.cloud is not CloudName.COMMERCIAL:
        row = default_matrix().by_id(_ROW_GOV)
        reason = row.notes if row and row.notes else "Foundry write support unverified (G01)"
        raise CapabilityUnavailableError("deployment_write_unavailable", reason)


class FoundryModelSwapAdvisoryConnector(AdvisoryWriteMixin):
    """Read-only/unsupported target: ``advisory`` is True and every write method raises."""

    def __init__(self, account: AccountRef, *, reason: str) -> None:
        self.account = account
        self.reason = reason

    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest(advisory=True)


class FoundryModelSwapConnector:
    """Write connector for a Foundry deployment model swap (one account)."""

    def __init__(
        self,
        account: AccountRef,
        arm: ArmClient,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        today: Today = _today,
        poll_interval_seconds: float = 5.0,
        poll_timeout_seconds: float = 300.0,
    ) -> None:
        self.account = account
        self._arm = arm
        self._sleep = sleep
        self._clock = clock
        self._today = today
        self._interval = poll_interval_seconds
        self._timeout = poll_timeout_seconds

    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest(advisory=False)

    @property
    def advisory(self) -> bool:
        return False

    # -- helpers ---------------------------------------------------------------------------

    def _deployment_name(self, target: TargetRef) -> str:
        if target.entity_type != "model_deployment":
            raise InvalidSchemaError("target is not a model deployment", reason="wrong_entity")
        cloud, _, rest = target.canonical_id.partition(":")
        if cloud != self.account.cloud.value:
            raise InvalidSchemaError("target cloud differs from connector", reason="cloud_mismatch")
        name = rest.split(":", 3)[3] if rest.count(":") >= 3 else ""
        try:
            return validate_name("deployment", name)
        except ValueError:
            raise InvalidSchemaError("invalid deployment name", reason="wrong_entity") from None

    async def _current(self, name: str, expected_etag: str | None) -> dict[str, Any]:
        current = await self._arm.get_deployment(name)
        if expected_etag is not None and str(current.get("etag", "")) != expected_etag:
            raise StaleVersionError("deployment changed", reason="target_version_changed")
        return current

    async def check_compatibility(self, request: WriteRequest) -> list[CompatCheck]:
        """Run the compatibility checks; ``unknown`` entries are warnings. Writes nothing."""
        _refuse_cloud(self.account)
        name = self._deployment_name(request.target)
        current = await self._current(name, request.target_version)
        return await self._checks(current, request.proposed_diff)

    async def _checks(self, current: dict[str, Any], diff: ProposedDiff) -> list[CompatCheck]:
        patched = apply_patch(current, diff)
        models = await self._arm.list_models()
        return run_compatibility(
            current=current,
            target_model=model_of(patched),
            models=models,
            today=self._today(),
        )

    @staticmethod
    def _require_passed(checks: list[CompatCheck]) -> None:
        failed = [c.check_id for c in checks if c.status == "failed"]
        if failed:
            raise InvalidSchemaError(
                "compatibility check failed: " + ", ".join(failed),
                reason="compatibility_failed",
            )

    async def _await_terminal(self, name: str, first: dict[str, Any]) -> dict[str, Any]:
        """Poll the deployment until provisioningState is terminal (bounded)."""
        deadline = self._clock() + self._timeout
        state = first
        while True:
            props = state.get("properties")
            prov = str(props.get("provisioningState", "")) if isinstance(props, dict) else ""
            if prov == "Succeeded":
                return state
            if prov in TERMINAL_FAILURE_STATES:
                raise CapabilityUnavailableError(
                    "provisioning_failed", f"deployment provisioningState is {prov}"
                )
            if self._clock() >= deadline:
                raise DependencyTransientError(reason="poll_timeout")
            await self._sleep(self._interval)
            state = await self._arm.get_deployment(name)

    # -- WriteConnector --------------------------------------------------------------------

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        _refuse_cloud(self.account)
        name = self._deployment_name(request.target)
        current = await self._current(name, request.target_version)
        patched = apply_patch(current, request.proposed_diff)
        self._require_passed(await self._checks(current, request.proposed_diff))
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=model_of(patched) != model_of(current),
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        _refuse_cloud(self.account)
        name = self._deployment_name(request.target)
        current = await self._current(name, request.target_version)
        patched = apply_patch(current, request.proposed_diff)
        self._require_passed(await self._checks(current, request.proposed_diff))
        prior = model_of(current)
        # Re-read immediately before the write: If-Match is not documented for this PUT.
        latest = await self._current(name, request.target_version)
        try:
            put = await self._arm.put_deployment(name, build_put_body(latest, model_of(patched)))
            final = await self._await_terminal(name, put)
        except Exception as cause:
            # The PUT may have reached ARM (even when its response was lost), so the real
            # deployment may have changed and no ApplyResult will reach the executor. Restore
            # the prior model here; the error is not retryable.
            restored = await self._restore_prior(name, latest, prior)
            reason = "apply_failed_restored" if restored else "apply_failed_restore_failed"
            raise CapabilityUnavailableError(
                reason, f"apply failed after the PUT ({_describe(cause)}); restored={restored}"
            ) from cause
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=str(final.get("etag", "")) or None,
            applied_diff=request.proposed_diff,
            rollback_token=json.dumps(prior, separators=(",", ":"), sort_keys=True),
        )

    async def _restore_prior(
        self, name: str, latest: dict[str, Any], prior: dict[str, str]
    ) -> bool:
        """Best-effort restore of the prior model after a failed apply; True when it settled."""
        try:
            put = await self._arm.put_deployment(name, build_put_body(latest, prior))
            await self._await_terminal(name, put)
        except Exception:
            return False
        return True

    async def verify(self, request: WriteRequest) -> VerifyResult:
        _refuse_cloud(self.account)
        name = self._deployment_name(request.target)
        observed = await self._arm.get_deployment(name)
        expected = request.model_copy(
            update={"proposed_diff": verification_diff(request.proposed_diff)}
        )
        result = build_verify_result(
            expected, observed, observed_version=str(observed.get("etag", "")) or None
        )
        props = observed.get("properties")
        prov = props.get("provisioningState") if isinstance(props, dict) else None
        if prov == "Succeeded":
            return result
        failed = OperationCheck(
            op="test", path="/properties/provisioningState", matched=False, observed=prov
        )
        return result.model_copy(update={"checks": (*result.checks, failed)})

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        _refuse_cloud(self.account)
        name = self._deployment_name(applied.target)
        prior = self._parse_token(applied.rollback_token)
        current = await self._current(name, applied.version_after)
        if model_of(current) == prior:
            return RollbackResult(
                target=applied.target,
                status="not_needed",
                version_after=str(current.get("etag", "")) or None,
            )
        put = await self._arm.put_deployment(name, build_put_body(current, prior))
        final = await self._await_terminal(name, put)
        return RollbackResult(
            target=applied.target,
            status="rolled_back",
            version_after=str(final.get("etag", "")) or None,
        )

    @staticmethod
    def _parse_token(token: str | None) -> dict[str, str]:
        try:
            raw = json.loads(token) if token else None
        except ValueError:
            raw = None
        if not isinstance(raw, dict) or set(raw) != {"format", "name", "version"}:
            raise InvalidSchemaError("rollback token is not usable", reason="bad_rollback_token")
        return {k: str(v) for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType]


async def create_swap_connector(
    account: AccountRef,
    credential: AsyncTokenCredential,
    *,
    client: httpx.AsyncClient | None = None,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = time.monotonic,
    today: Today = _today,
    poll_interval_seconds: float = 5.0,
    poll_timeout_seconds: float = 300.0,
) -> FoundryModelSwapConnector | FoundryModelSwapAdvisoryConnector:
    """Write connector when the credential can write deployments, else the advisory one.

    Government accounts and any permission shortfall (including a 403 on the permission read
    itself) yield the advisory connector; only reads (GET permissions) are issued here.
    """
    if account.cloud is not CloudName.COMMERCIAL:
        return FoundryModelSwapAdvisoryConnector(
            account, reason="Government deployment write unverified (G01)"
        )
    arm = ArmClient(account, credential, client=client)
    try:
        permissions = await arm.list_permissions()
    except ForbiddenError:
        await arm.close()
        return FoundryModelSwapAdvisoryConnector(
            account, reason="permissions could not be read; write access unproven"
        )
    except BaseException:
        await arm.close()
        raise
    if not can_write_deployments(permissions):
        await arm.close()
        return FoundryModelSwapAdvisoryConnector(
            account, reason=f"{DEPLOYMENT_WRITE_ACTION} is not granted"
        )
    return FoundryModelSwapConnector(
        account,
        arm,
        sleep=sleep,
        clock=clock,
        today=today,
        poll_interval_seconds=poll_interval_seconds,
        poll_timeout_seconds=poll_timeout_seconds,
    )
