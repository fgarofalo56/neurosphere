"""APIM AI gateway write connector (PRP-34 item 1): plan, apply, verify, rollback.

Shape follows ``foundry-actions``: a write connector plus a separate advisory connector (the
registry refuses advisory connectors as action targets), a Government refusal driven by the
capability matrix, ``dry_run`` against ``target_version``, ``apply`` returning an ``ApplyResult``
whose token points at the ownership record, ``verify`` from a real read-back via
``build_verify_result``, and ``rollback`` from the ``ApplyResult``.

Every change is a ``PublishPlan`` (see ``models``). ``dry_run`` plans and returns the diff with
the plan digest bound in as ``test /plan_digest``; ``apply`` re-plans against the live gateway
and refuses (``stale_version`` reason ``plan_digest_mismatch``) when the digest differs from
the reviewed one, then the applier writes in dependency order with existence re-read, If-Match
and ownership recorded per step. The connector never calls ``listSecrets`` (the ARM layer has
no POST) and never logs payloads or policy XML.

Only the worker executor may call ``apply`` and ``rollback`` (PRP-17 D5); item 2 extends the
repo-wide test to this package.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol, cast, get_args, runtime_checkable

from neurosphere_connector import build_manifest
from neurosphere_connector.manifest import WriteAction
from neurosphere_connector.write import (
    AdvisoryWriteMixin,
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    build_verify_result,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.capabilities.validate import default_matrix
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway.mode import MODE_CHANGE_KIND

from neurosphere_connector_apim_gateway.applier import PlanApplier
from neurosphere_connector_apim_gateway.arm import ApimArm
from neurosphere_connector_apim_gateway.cap import AttributeChange
from neurosphere_connector_apim_gateway.compare import payload_matches
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.mode import MODE_TARGET_TYPE, GatewayModeHandler
from neurosphere_connector_apim_gateway.models import PublishPlan, ResourceSpec
from neurosphere_connector_apim_gateway.planner import build_plan
from neurosphere_connector_apim_gateway.records import ApplyRecordStore
from neurosphere_connector_apim_gateway.translate import (
    GatewayResourcesTranslator,
    IntentTranslator,
    escape_token,
    reviewed_digest,
    with_digest,
)

__all__ = [
    "ACTION_KINDS",
    "ACTION_KIND_MISMATCH",
    "ADVISORY_CONNECTOR_NAME",
    "CONNECTOR_NAME",
    "GOVERNMENT_ROW",
    "ApimGatewayAdvisoryConnector",
    "ApimGatewayConnector",
    "create_apim_connector",
    "manifest_actions",
]

CONNECTOR_NAME: Final = "apim-gateway"
ADVISORY_CONNECTOR_NAME: Final = "apim-gateway-advisory"
DOCUMENTATION_URL: Final = (
    "https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities"
)
# PRP-34 Clarification 10: the action kinds this connector serves. The manifest can only list
# kinds the connector-manifest contract enum admits (see ``manifest_actions``).
ACTION_KINDS: Final = (
    "model_deployment_swap",
    "budget_cap_change",
    "grant_publish",
    "grant_unpublish",
    "mcp_server_publish",
    "mcp_server_unpublish",
    # PRP-34 item 2: the audited observe/manage switch (target ``apim_gateway_mode``).
    "gateway_mode_change",
)
# v2 tiers are unverified in Government (PRP-34 gotcha); manage stays disabled until this row
# says ``available``.
GOVERNMENT_ROW: Final = "apim.backend_pool.government.any.standard_v2"
#: Refusal when a diff grammar does not belong to the intent's action kind (PRP-34 item 10).
ACTION_KIND_MISMATCH: Final = "action_kind_mismatch"


@runtime_checkable
class _Previewing(Protocol):
    """A translator that offers a before/after attribute preview (the budget cap)."""

    async def preview(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> list[AttributeChange]: ...


def manifest_actions() -> list[WriteAction]:
    """``ACTION_KINDS`` filtered to the contract's ``write_support.actions`` enum."""
    allowed = set(get_args(WriteAction))
    return [cast(WriteAction, k) for k in ACTION_KINDS if k in allowed]


def _manifest(*, advisory: bool) -> ConnectorManifest:
    return build_manifest(
        name=ADVISORY_CONNECTOR_NAME if advisory else CONNECTOR_NAME,
        version="0.1.0",
        capabilities=["health_reporting"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="unknown", subject_level="deployment"),
        scopes=["https://management.azure.com/.default"],
        write_actions=[] if advisory else manifest_actions(),
        documentation_url=DOCUMENTATION_URL,
    )


def government_refusal(cloud: CloudName) -> CapabilityUnavailableError | None:
    """The refusal for a non-Commercial gateway, or None when manage may run."""
    if cloud is CloudName.COMMERCIAL:
        return None
    row = default_matrix().by_id(GOVERNMENT_ROW)
    if row is not None and row.availability == "available":
        return None
    reason = (
        row.notes
        if row is not None and row.notes
        else "APIM v2 tiers are unverified in Azure Government"
    )
    return CapabilityUnavailableError("gateway_manage_unavailable", reason)


class ApimGatewayAdvisoryConnector(AdvisoryWriteMixin):
    """Read-only/unsupported gateway: ``advisory`` is True and every write method raises."""

    def __init__(self, gateway: GatewayRef, *, reason: str) -> None:
        self.gateway = gateway
        self.reason = reason

    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest(advisory=True)


class ApimGatewayConnector:
    """Write connector for one registered APIM gateway (Commercial)."""

    def __init__(
        self,
        gateway: GatewayRef,
        arm: ApimArm,
        *,
        records: ApplyRecordStore,
        mode: GatewayModeHandler,
        translators: Sequence[IntentTranslator] = (),
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        # Required (PRP-34 item 2 review): without a mode handler the observe-mode guard would
        # be skipped, so a missing handler is refused at construction (fail closed).
        if not isinstance(mode, GatewayModeHandler):
            raise TypeError("a GatewayModeHandler is required (observe-mode guard)")
        if mode.gateway != gateway:
            raise ValueError("the mode handler is bound to another gateway")
        self.gateway = gateway
        self._arm = arm
        self._records = records
        # PRP-34 item 2: ``gateway_mode_change`` runs through the handler and every resource
        # plan first requires the gateway to be in manage mode (``gateway_observe_mode``).
        self._mode = mode
        self._applier = (
            PlanApplier(arm, records, id_factory=id_factory)
            if id_factory is not None
            else PlanApplier(arm, records)
        )
        self._translators: dict[str, IntentTranslator] = {}
        for translator in (GatewayResourcesTranslator(), *translators):
            self.register_translator(translator)

    def register_translator(self, translator: IntentTranslator) -> None:
        """Add (or replace) the translator for each of its target entity types."""
        for entity_type in translator.entity_types:
            self._translators[entity_type] = translator

    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest(advisory=False)

    @property
    def advisory(self) -> bool:
        return False

    # -- helpers ---------------------------------------------------------------------------

    def _refuse_cloud(self) -> None:
        refusal = government_refusal(self.gateway.cloud)
        if refusal is not None:
            raise refusal

    @staticmethod
    def _is_mode_change(target_entity_type: str) -> bool:
        return target_entity_type == MODE_TARGET_TYPE

    def _mode_handler(self) -> GatewayModeHandler:
        return self._mode

    def _translator(self, request: WriteRequest) -> IntentTranslator:
        translator = self._translators.get(request.target.entity_type)
        if translator is None:
            raise InvalidSchemaError(
                "target kind is not handled by the APIM connector", reason="wrong_entity"
            )
        return translator

    async def _current_version(self, translator: IntentTranslator, request: WriteRequest) -> str:
        return await translator.current_version(self._arm, self.gateway, request)

    async def _plan(
        self, request: WriteRequest
    ) -> tuple[IntentTranslator, PublishPlan, list[ResourceSpec]]:
        self._refuse_cloud()
        translator = self._translator(request)
        await self._mode.require_manage()
        specs = translator.specs(self.gateway, request)
        current = await self._current_version(translator, request)
        if current != request.target_version:
            raise StaleVersionError("target changed", reason="target_version_changed")
        plan = await build_plan(
            self._arm,
            gateway_id=self.gateway.gateway_id,
            target=request.target.canonical_id,
            target_version=request.target_version,
            specs=specs,
        )
        return translator, plan, specs

    async def plan(self, request: WriteRequest) -> PublishPlan:
        """The plan for ``request`` against the live gateway; reads only."""
        _, plan, _ = await self._plan(request)
        return plan

    @staticmethod
    def _check_reviewed(request: WriteRequest, plan: PublishPlan, *, required: bool) -> None:
        reviewed = reviewed_digest(request.proposed_diff)
        if reviewed is None:
            if required:
                raise InvalidSchemaError(
                    "apply needs the reviewed plan digest (test /plan_digest)",
                    reason="plan_digest_required",
                )
            return
        if reviewed != plan.digest:
            raise StaleVersionError(
                "the plan no longer matches the reviewed plan", reason="plan_digest_mismatch"
            )

    def check_action(self, action_kind: str, request: WriteRequest) -> None:
        """Refuse a diff whose grammar does not belong to ``action_kind`` (PRP-34 item 10).

        ``WriteRequest`` carries no action kind, so the executor (at connector resolution) and
        the API planning view call this before any plan: a ``remove`` stage under
        ``mcp_server_publish``, an unpublish diff under ``grant_publish`` or a cap diff under a
        publication kind is ``invalid_schema`` reason ``action_kind_mismatch``. Pure; no I/O.
        """
        mode_target = self._is_mode_change(request.target.entity_type)
        if mode_target != (action_kind == MODE_CHANGE_KIND):
            raise InvalidSchemaError(
                "the mode switch has its own action kind and target", reason=ACTION_KIND_MISMATCH
            )
        if mode_target:
            return
        # An unhandled target kind is refused by dry_run itself (``wrong_entity``).
        translator = self._translators.get(request.target.entity_type)
        check = getattr(translator, "check_kind", None)
        if callable(check):
            check(action_kind, request)

    async def preview(self, request: WriteRequest) -> list[AttributeChange]:
        """Before/after attribute diff of a change whose translator offers one (a cap change:
        the ``llm-token-limit`` attributes of the live fragment and of the rendered one). Reads
        only, with the same cloud and observe-mode refusals as ``dry_run``; empty otherwise."""
        self._refuse_cloud()
        if self._is_mode_change(request.target.entity_type):
            return []
        translator = self._translator(request)
        await self._mode.require_manage()
        if not isinstance(translator, _Previewing):
            return []
        return list(await translator.preview(self._arm, self.gateway, request))

    # -- WriteConnector --------------------------------------------------------------------

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        if self._is_mode_change(request.target.entity_type):
            return await self._mode_handler().dry_run(request)
        _, plan, _ = await self._plan(request)
        self._check_reviewed(request, plan, required=False)
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=with_digest(request.proposed_diff, plan.digest),
            would_change=plan.would_change,
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        if self._is_mode_change(request.target.entity_type):
            return await self._mode_handler().apply(request)
        translator, plan, specs = await self._plan(request)
        self._check_reviewed(request, plan, required=True)
        record = await self._applier.apply(plan, specs)
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=await self._current_version(translator, request),
            applied_diff=request.proposed_diff,
            rollback_token=record.id,
        )

    async def verify(self, request: WriteRequest) -> VerifyResult:
        """Read every planned resource back. Observed state holds booleans, never payloads."""
        if self._is_mode_change(request.target.entity_type):
            return await self._mode_handler().verify(request)
        self._refuse_cloud()
        translator = self._translator(request)
        specs = translator.specs(self.gateway, request)
        observed: dict[str, Any] = {}
        checks: list[PatchOperation] = []
        for spec in specs:
            current = await self._arm.get(spec.name)
            token = escape_token(spec.name)
            if spec.operation == "delete":
                if current is not None:
                    observed[spec.name] = {"present": True, "matched": False}
                checks.append(PatchOperation(op="remove", path=f"/resources/{token}"))
                continue
            matched = current is not None and payload_matches(
                spec.resource_type, spec.payload or {}, current.properties
            )
            observed[spec.name] = {"present": current is not None, "matched": matched}
            checks.append(PatchOperation(op="test", path=f"/resources/{token}/matched", value=True))
        expected = request.model_copy(
            update={"proposed_diff": ProposedDiff(format="json_patch", operations=checks)}
        )
        return build_verify_result(
            expected,
            {"resources": observed},
            observed_version=await self._current_version(translator, request),
        )

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        """Run the reverse plan of a succeeded apply from its ownership record."""
        if self._is_mode_change(applied.target.entity_type):
            return await self._mode_handler().rollback(applied)
        self._refuse_cloud()
        record = (
            await self._records.latest(applied.rollback_token) if applied.rollback_token else None
        )
        if record is None or record.target != applied.target.canonical_id:
            raise InvalidSchemaError("rollback token is not usable", reason="bad_rollback_token")
        if record.status == "rolled_back":
            return RollbackResult(target=applied.target, status="not_needed")
        await self._applier.reverse(record)
        return RollbackResult(target=applied.target, status="rolled_back")


def create_apim_connector(
    gateway: GatewayRef,
    arm: ApimArm,
    *,
    records: ApplyRecordStore,
    mode: GatewayModeHandler,
    translators: Sequence[IntentTranslator] = (),
) -> ApimGatewayConnector | ApimGatewayAdvisoryConnector:
    """Write connector for a Commercial gateway; the advisory one where manage is disabled.

    ``mode`` (PRP-34 item 2, required) wires the observe/manage switch: ``gateway_mode_change``
    runs the permissions preflight and flips the registration, and resource plans require
    manage mode.
    """
    refusal = government_refusal(gateway.cloud)
    if refusal is not None:
        return ApimGatewayAdvisoryConnector(gateway, reason=refusal.detail or "manage disabled")
    return ApimGatewayConnector(gateway, arm, records=records, translators=translators, mode=mode)
