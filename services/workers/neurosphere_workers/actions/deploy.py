"""Deploy apply / uninstall-preview write connector for the action executor (PRP-08 item 12).

The deploy plan is applied by the SAME executor as every other governed change: this module is a
:class:`~neurosphere_connector.write.WriteConnector`, registered in the executor's
``WriteTargetRegistry`` under :data:`DEPLOY_CONNECTOR`, that serves two action kinds.

``deploy_plan_apply`` (target ``<cloud>:<customer>:deploy:deployment_plan:<plan_id>``, target
version = the plan hash)
    The ``proposed_diff`` is ``test /plan_hash``, ``test /resources_digest``, ``test
    /deployment_id`` and one ``add /resources/<service>.<kind>`` per resource of the
    :class:`~neurosphere_contracts.deployment.v1.deploy_action_plan.DeployActionPlan`. Every
    phase (``dry_run``, ``apply``, ``verify``) re-checks, before any network call, that

    * the plan is approved (``plan_not_approved``) and its approved hash and approved resource
      digest equal the diff and the intent's target version (``plan_hash_mismatch``,
      ``resources_not_approved``),
    * the connector's cloud is the plan's cloud (``cloud_mismatch``; never bridged), and
    * every Fabric item is available per the capability matrix. Otherwise the whole intent is
      refused with ``capability_unavailable`` and ZERO HTTP calls are made.

    Fabric capacity and workspace go through :class:`FabricProvisioner`; any other service
    through an injected :class:`ArmProvisioner` (none configured = ``capability_unavailable``).
    A resource that already exists was not created by this plan and is never claimed
    (``resource_exists_not_owned``). Every created ARM resource is recorded in the ownership
    register right after it is created; reused resources are recorded as ``reused`` with their
    consent reference and are never modified. ``verify`` reads the real targets back (read-only
    GETs) so a pretend apply shows up as a mismatch. There is no rollback: undoing a deployment is
    the guarded uninstall path, never an automatic delete.

``deploy_uninstall`` (target ``<cloud>:<customer>:deploy:deployment:<deployment_id>``, target
version = the register digest)
    DRY-RUN ONLY. ``dry_run`` plans the removal with the R1 guard (``plan_removal``: only rows the
    register records as ``created``, no foreign dependents, resource groups only when their live
    contents are verified) and returns the plan as a diff. ``apply`` always refuses
    (``uninstall_dry_run_only``). This class holds no :class:`ResourceDeleter`, so no delete call
    is reachable through it by construction; the guarded ``remove`` stays operator-run
    (``infra/scripts/uninstall.py`` under ``NS_LIVE_APPROVED=1``).

No secret is read or written: the diff and the register hold ids, names and digests only.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import quote, urlsplit

from neurosphere_connector import build_manifest
from neurosphere_connector.write import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    build_verify_result,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_contracts.deployment.v1.deploy_action_plan import DeployActionPlan, ResourceSpec
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.capabilities import CapabilityMatrix, DeploymentProfile, validate_profile
from neurosphere_core.cloud import CloudName
from neurosphere_core.deploy.fabric import FabricEndpoints, FabricHttp, FabricProvisioner
from neurosphere_core.deploy.fabric.provisioner import ARM_API_VERSION
from neurosphere_core.deploy.register import (
    LiveInventory,
    Ownership,
    RegisterStore,
    RemovalPlan,
    ResourceRow,
    normalize_id,
    plan_removal,
)
from neurosphere_core.deploy.register.guard import is_resource_group
from neurosphere_core.deploy.register.models import CREATED_BY_NEUROSPHERE
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)
from pydantic import ValidationError

__all__ = [
    "APPLY_KIND",
    "DEPLOYMENT_ENTITY",
    "DEPLOY_ACTION_CONNECTORS",
    "DEPLOY_CONNECTOR",
    "PLAN_ENTITY",
    "UNINSTALL_KIND",
    "ApprovedPlan",
    "ArmProvisioner",
    "DeployConnector",
    "FabricHttpObserver",
    "FabricObserver",
    "PlanApprovals",
    "ProvisionedResource",
    "apply_diff",
    "deployment_target",
    "fabric_unavailable_reason",
    "plan_target",
    "register_digest",
    "resource_key",
    "resources_digest",
    "uninstall_diff",
    "uninstall_preview",
]

DEPLOY_CONNECTOR: Final = "deploy-orchestrator"
APPLY_KIND: Final = "deploy_plan_apply"
UNINSTALL_KIND: Final = "deploy_uninstall"
PLAN_ENTITY: Final = "deployment_plan"
DEPLOYMENT_ENTITY: Final = "deployment"

#: ``action_kind`` -> connector name. Merge into the executor's ``action_connectors`` table:
#: ``{**DEFAULT_ACTION_CONNECTORS, **DEPLOY_ACTION_CONNECTORS}``.
DEPLOY_ACTION_CONNECTORS: Final[Mapping[str, str]] = MappingProxyType(
    {APPLY_KIND: DEPLOY_CONNECTOR, UNINSTALL_KIND: DEPLOY_CONNECTOR}
)

SCHEMA_VERSION: Final = "1.0.0"
PLAN_HASH_PATH: Final = "/plan_hash"
RESOURCES_DIGEST_PATH: Final = "/resources_digest"
DEPLOYMENT_ID_PATH: Final = "/deployment_id"
REGISTER_DIGEST_PATH: Final = "/register_digest"
RESOURCES_PREFIX: Final = "/resources/"

CAPABILITY_UNAVAILABLE: Final = "capability_unavailable"
PLAN_NOT_APPROVED: Final = "plan_not_approved"
PLAN_HASH_MISMATCH: Final = "plan_hash_mismatch"
RESOURCES_NOT_APPROVED: Final = "resources_not_approved"
CLOUD_MISMATCH: Final = "cloud_mismatch"
EXISTS_NOT_OWNED: Final = "resource_exists_not_owned"
UNINSTALL_DRY_RUN_ONLY: Final = "uninstall_dry_run_only"
ROLLBACK_NOT_SUPPORTED: Final = "rollback_not_supported"
TARGET_VERSION_CHANGED: Final = "target_version_changed"

#: Pseudonymous owner recorded on register rows written by the executor.
SYSTEM_OWNER: Final = "svc.neurosphere-actions"
_CAPACITY_NAME: Final = re.compile(r"^[a-z][a-z0-9]{2,62}$")
_ARM_ID_TAIL: Final = re.compile(r"[^/]+$")
_MAX_WORKSPACE_PAGES: Final = 10


# -- approvals, provisioners, observers (injected; tests use stubs) ----------------------------


@dataclass(frozen=True, slots=True)
class ApprovedPlan:
    """What the approver approved: the plan hash and the digest of its executable resources."""

    customer_id: str
    plan_id: str
    plan_hash: str
    resources_digest: str
    deployment_id: str


@runtime_checkable
class PlanApprovals(Protocol):
    """Read side of the approval store the apply is checked against at execution time."""

    async def get(self, customer_id: str, plan_id: str) -> ApprovedPlan | None: ...


@dataclass(frozen=True, slots=True)
class ProvisionedResource:
    resource_id: str
    #: True only when this call created the resource; an existing one is never claimed.
    created: bool


class ArmProvisioner(Protocol):
    """Creates a non-Fabric resource through ARM (idempotent: reports ``created=False``)."""

    async def ensure(self, spec: ResourceSpec) -> ProvisionedResource: ...

    async def exists(self, spec: ResourceSpec) -> bool: ...


class FabricObserver(Protocol):
    """Read-only existence checks used by ``verify`` (never writes)."""

    async def capacity_exists(self, spec: ResourceSpec) -> bool: ...

    async def workspace_exists(self, spec: ResourceSpec) -> bool: ...


class FabricHttpObserver:
    """:class:`FabricObserver` over the same bearer-authenticated transport as the provisioner."""

    def __init__(self, http: FabricHttp, endpoints: FabricEndpoints) -> None:
        self._http = http
        self._ep = endpoints

    async def capacity_exists(self, spec: ResourceSpec) -> bool:
        arm_id = capacity_arm_id(spec)
        url = f"{self._ep.management_url.rstrip('/')}{arm_id}?api-version={ARM_API_VERSION}"
        response = await self._http.request("GET", url, None)
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise _upstream(response.status_code)
        return True

    async def workspace_exists(self, spec: ResourceSpec) -> bool:
        url: str | None = f"{self._ep.fabric_api_base.rstrip('/')}/v1/workspaces"
        for _ in range(_MAX_WORKSPACE_PAGES):
            response = await self._http.request("GET", url, None)
            if response.status_code != 200:
                raise _upstream(response.status_code)
            body = response.body or {}
            if any(item.get("displayName") == spec.name for item in body.get("value", [])):
                return True
            url = body.get("continuationUri")
            if not url or (urlsplit(url).hostname or "").lower() not in self._ep.allowed_hosts:
                return False
        return False


def _upstream(status: int) -> DependencyTransientError:
    return DependencyTransientError(
        f"unexpected upstream status {status}", reason="unexpected_status", upstream_invalid=True
    )


# -- diff construction and parsing (shared with the API) ----------------------------------------


def escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def resource_key(spec: ResourceSpec) -> str:
    """Stable, pointer-safe key of one resource inside the diff."""
    return f"{spec.service}.{spec.kind}"


def resources_digest(resources: Sequence[ResourceSpec]) -> str:
    return sha256_digest([r.model_dump(mode="json") for r in resources])


def plan_target(cloud: str, customer_id: str, plan_id: str) -> TargetRef:
    return TargetRef(
        canonical_id=f"{cloud}:{customer_id}:deploy:{PLAN_ENTITY}:{plan_id}",
        entity_type=PLAN_ENTITY,
    )


def deployment_target(cloud: str, customer_id: str, deployment_id: str) -> TargetRef:
    return TargetRef(
        canonical_id=f"{cloud}:{customer_id}:deploy:{DEPLOYMENT_ENTITY}:{deployment_id}",
        entity_type=DEPLOYMENT_ENTITY,
    )


def _split_target(target: TargetRef, entity: str) -> tuple[str, str, str]:
    """(cloud, customer, tail id) of a deploy target, or ``invalid_schema``."""
    parts = target.canonical_id.split(":", 4)
    if (
        target.entity_type != entity
        or len(parts) != 5
        or parts[2] != "deploy"
        or parts[3] != entity
    ):
        raise InvalidSchemaError("not a deploy target of this kind", reason="unsupported_target")
    return parts[0], parts[1], parts[4]


def _test(path: str, value: str) -> PatchOperation:
    return PatchOperation(op="test", path=path, value=value)


def apply_diff(plan: DeployActionPlan) -> ProposedDiff:
    """The diff the maker confirms and the approver decides on: hash, digest and every resource."""
    operations = [
        _test(PLAN_HASH_PATH, plan.plan_hash),
        _test(RESOURCES_DIGEST_PATH, resources_digest(plan.resources)),
        _test(DEPLOYMENT_ID_PATH, plan.deployment_id),
        *(
            PatchOperation(
                op="add",
                path=RESOURCES_PREFIX + escape_pointer(resource_key(spec)),
                value=spec.model_dump(mode="json"),
            )
            for spec in plan.resources
        ),
    ]
    return ProposedDiff(format="json_patch", operations=operations)


@dataclass(frozen=True, slots=True)
class _ParsedApply:
    plan_hash: str
    digest: str
    deployment_id: str
    resources: tuple[ResourceSpec, ...]


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _parse_apply(diff: ProposedDiff) -> _ParsedApply:
    tests: dict[str, str] = {}
    resources: list[ResourceSpec] = []
    try:
        for op in diff.operations:
            if op.op == "test" and isinstance(op.value, str):
                tests[op.path] = op.value
            elif op.op == "add" and op.path.startswith(RESOURCES_PREFIX):
                spec = ResourceSpec.model_validate(op.value)
                if _unescape(op.path[len(RESOURCES_PREFIX) :]) != resource_key(spec):
                    raise ValueError("resource path does not match its spec")
                resources.append(spec)
            else:
                raise ValueError("unexpected diff operation")
        plan_hash = tests[PLAN_HASH_PATH]
        digest = tests[RESOURCES_DIGEST_PATH]
        deployment_id = tests[DEPLOYMENT_ID_PATH]
    except (KeyError, ValueError, ValidationError):
        raise InvalidSchemaError(
            "the diff is not a deploy plan apply diff", reason="diff_malformed"
        ) from None
    if len({resource_key(r) for r in resources}) != len(resources):
        raise InvalidSchemaError("duplicate resource in the diff", reason="diff_malformed")
    return _ParsedApply(plan_hash, digest, deployment_id, tuple(resources))


def register_digest(rows: Sequence[ResourceRow]) -> str:
    """Order-independent digest of one deployment's register rows (uninstall target version)."""
    ordered = sorted(rows, key=lambda r: normalize_id(r.resource_id))
    return sha256_digest([r.model_dump(mode="json") for r in ordered])


def uninstall_diff(digest: str, removable_ids: Sequence[str]) -> ProposedDiff:
    """Dry-run diff: the register digest it was planned against and each removable resource."""
    operations = [
        _test(REGISTER_DIGEST_PATH, digest),
        *(
            PatchOperation(op="remove", path=RESOURCES_PREFIX + escape_pointer(rid))
            for rid in removable_ids
        ),
    ]
    return ProposedDiff(format="json_patch", operations=operations)


async def uninstall_preview(
    deployment_id: str,
    rows: Sequence[ResourceRow],
    inventory: LiveInventory | None = None,
) -> RemovalPlan:
    """The R1-guarded removal plan, read-only. Resource groups are only removable when
    ``inventory`` lists their live contents and every one is a registered ``created`` row; a
    listing failure keeps the group (and so everything it holds) untouched."""
    live: dict[str, list[str]] | None = None
    if inventory is not None:
        live = {}
        for row in rows:
            if is_resource_group(row.resource_id):
                try:
                    live[row.resource_id] = await inventory.list_resource_group(row.resource_id)
                except Exception:
                    live[row.resource_id] = [f"{row.resource_id}/unlistable"]
    return plan_removal(deployment_id, rows, live_contents=live)


# -- capability gate -----------------------------------------------------------------------------


def fabric_unavailable_reason(
    cloud: CloudName, region: str, matrix: CapabilityMatrix | None = None
) -> str | None:
    """``None`` when the capability matrix supports Fabric for ``cloud``/``region``, else the
    machine reason. Pure: no network."""
    try:
        profile = DeploymentProfile(
            cloud=cloud.value,  # type: ignore[arg-type]
            regions=(region,),
            hosting="aks",
            analytics="fabric",
        )
    except ValidationError:
        return "invalid_region"
    for item in validate_profile(profile, matrix=matrix).results:
        if item.kind == "analytics" and item.status != "supported":
            return item.reason_code or "not_verified"
    return None


def capacity_arm_id(spec: ResourceSpec) -> str:
    if not (spec.subscription_id and spec.resource_group and _CAPACITY_NAME.fullmatch(spec.name)):
        raise InvalidSchemaError(
            "a Fabric capacity needs a subscription, resource group and valid name",
            reason="invalid_resource_spec",
        )
    return (
        f"/subscriptions/{spec.subscription_id}/resourceGroups/{quote(spec.resource_group)}"
        f"/providers/Microsoft.Fabric/capacities/{spec.name}"
    )


# -- the connector -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Checked:
    customer_id: str
    plan_id: str
    parsed: _ParsedApply


class DeployConnector:
    """Write connector for ``deploy_plan_apply`` and the dry-run-only ``deploy_uninstall``.

    ``cloud`` binds the connector to one cloud. ``fabric``/``observer`` are required to apply
    Fabric items and ``arm`` to apply any other service; a missing one makes such an item
    ``capability_unavailable`` (fail closed). ``inventory`` is the read-only live listing used to
    verify resource groups in an uninstall preview. There is deliberately no deleter.
    """

    def __init__(
        self,
        *,
        cloud: CloudName,
        approvals: PlanApprovals,
        register: RegisterStore,
        fabric: FabricProvisioner | None = None,
        observer: FabricObserver | None = None,
        arm: ArmProvisioner | None = None,
        inventory: LiveInventory | None = None,
        matrix: CapabilityMatrix | None = None,
    ) -> None:
        self._cloud = cloud
        self._approvals = approvals
        self._register = register
        self._fabric = fabric
        self._observer = observer
        self._arm = arm
        self._inventory = inventory
        self._matrix = matrix

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name=DEPLOY_CONNECTOR,
            version="0.1.0",
            capabilities=["health_reporting"],
            supported_clouds=[self._cloud.value],  # type: ignore[list-item]
            granularity=Granularity(time_grain="unknown", subject_level="deployment"),
            write_actions=[APPLY_KIND, UNINSTALL_KIND],
        )

    @property
    def advisory(self) -> bool:
        return False

    # -- WriteConnector ------------------------------------------------------------------------

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        if request.target.entity_type == DEPLOYMENT_ENTITY:
            return await self._uninstall_dry_run(request)
        checked = await self._check_apply(request)
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=any(r.disposition == "create" for r in checked.parsed.resources),
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        if request.target.entity_type == DEPLOYMENT_ENTITY:
            raise ForbiddenError(
                "uninstall is a dry-run preview only; removal is an operator-run guarded script",
                reason=UNINSTALL_DRY_RUN_ONLY,
            )
        checked = await self._check_apply(request)
        for spec in checked.parsed.resources:
            await self._apply_one(checked, spec)
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after=None,
            applied_diff=request.proposed_diff,
            rollback_token=None,
        )

    async def verify(self, request: WriteRequest) -> VerifyResult:
        if request.target.entity_type == DEPLOYMENT_ENTITY:
            rows = await self._register.list_rows(self._deployment(request))
            # What is still registered: a ``remove`` operation only matches once the row is gone,
            # so an uninstall intent can never read back as applied while its rows remain.
            state: dict[str, Any] = {
                "register_digest": register_digest(rows),
                "resources": {row.resource_id: row.ownership.value for row in rows},
            }
            return build_verify_result(request, state)
        checked = await self._check_apply(request)
        approved = checked.parsed
        observed: dict[str, Any] = {}
        for spec in approved.resources:
            if await self._exists(approved.deployment_id, spec):
                observed[resource_key(spec)] = spec.model_dump(mode="json")
        state = {
            "plan_hash": approved.plan_hash,
            "resources_digest": approved.digest,
            "deployment_id": approved.deployment_id,
            "resources": observed,
        }
        return build_verify_result(request, state)

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        raise CapabilityUnavailableError(
            ROLLBACK_NOT_SUPPORTED,
            "a deploy apply is never rolled back automatically; uninstall is separate and guarded",
        )

    # -- apply checks ----------------------------------------------------------------------------

    async def _check_apply(self, request: WriteRequest) -> _Checked:
        cloud, customer_id, plan_id = _split_target(request.target, PLAN_ENTITY)
        parsed = _parse_apply(request.proposed_diff)
        if cloud != self._cloud.value:
            raise ForbiddenError("the plan is for another cloud", reason=CLOUD_MISMATCH)
        if request.target_version != parsed.plan_hash:
            raise ForbiddenError("the plan hash changed", reason=PLAN_HASH_MISMATCH)
        if resources_digest(parsed.resources) != parsed.digest:
            raise ForbiddenError(
                "the resources do not match their digest", reason=RESOURCES_NOT_APPROVED
            )
        approved = await self._approvals.get(customer_id, plan_id)
        if approved is None:
            raise ForbiddenError("the plan is not approved", reason=PLAN_NOT_APPROVED)
        if approved.plan_hash != parsed.plan_hash or approved.deployment_id != parsed.deployment_id:
            raise ForbiddenError("the plan changed since approval", reason=PLAN_HASH_MISMATCH)
        if approved.resources_digest != parsed.digest:
            raise ForbiddenError(
                "the resources differ from the approved ones", reason=RESOURCES_NOT_APPROVED
            )
        self._check_capabilities(parsed.resources)
        return _Checked(customer_id, plan_id, parsed)

    def _check_capabilities(self, resources: Sequence[ResourceSpec]) -> None:
        """Refuse before any network call when one item cannot be provisioned here."""
        for spec in resources:
            if spec.disposition == "reuse":
                if not (spec.resource_id and spec.consent_reference):
                    raise InvalidSchemaError(
                        "a reused resource needs its id and consent reference",
                        reason="invalid_resource_spec",
                    )
                continue
            if spec.kind == "arm_resource":
                if self._arm is None:
                    raise _unavailable("no ARM provisioner is configured for this service")
                continue
            reason = fabric_unavailable_reason(self._cloud, spec.region, self._matrix)
            if reason is not None:
                raise _unavailable(f"Fabric is not available in {spec.region}: {reason}")
            if self._fabric is None or self._observer is None:
                raise _unavailable("no Fabric provisioner is configured")

    # -- apply ---------------------------------------------------------------------------------

    async def _apply_one(self, checked: _Checked, spec: ResourceSpec) -> None:
        if spec.disposition == "reuse":
            assert spec.resource_id is not None
            await self._record(checked, spec, spec.resource_id, Ownership.REUSED)
        elif spec.kind == "fabric_capacity":
            assert self._fabric is not None
            capacity = await self._fabric.ensure_capacity(
                subscription_id=spec.subscription_id or "",
                resource_group=spec.resource_group or "",
                name=spec.name,
                region=spec.region,
                sku=spec.sku or "",
                admin_members=(),
            )
            if not capacity.created:
                raise ForbiddenError(
                    "the capacity already exists and was not created by this plan",
                    reason=EXISTS_NOT_OWNED,
                )
            await self._record(checked, spec, capacity.arm_id, Ownership.CREATED)
        elif spec.kind == "fabric_workspace":
            assert self._fabric is not None
            workspace = await self._fabric.ensure_workspace(
                display_name=spec.name, region=spec.region, capacity_id=None
            )
            if not workspace.created:
                raise ForbiddenError(
                    "the workspace already exists and was not created by this plan",
                    reason=EXISTS_NOT_OWNED,
                )
            # A Fabric workspace is not an ARM resource, so the ARM-id register has no row for it:
            # uninstall leaves it untouched (the safe direction).
        else:
            assert self._arm is not None
            provisioned = await self._arm.ensure(spec)
            if not provisioned.created:
                raise ForbiddenError(
                    "the resource already exists and was not created by this plan",
                    reason=EXISTS_NOT_OWNED,
                )
            await self._record(checked, spec, provisioned.resource_id, Ownership.CREATED)

    async def _record(
        self, checked: _Checked, spec: ResourceSpec, resource_id: str, ownership: Ownership
    ) -> None:
        created = ownership is Ownership.CREATED
        await self._register.put_row(
            ResourceRow(
                deployment_id=checked.parsed.deployment_id,
                resource_id=resource_id,
                service=spec.service,
                ownership=ownership,
                created_by=CREATED_BY_NEUROSPHERE if created else None,
                owner=SYSTEM_OWNER,
                consent_reference=None if created else spec.consent_reference,
                creating_plan_id=checked.plan_id,
                recorded_at=datetime.now(UTC),
            )
        )

    # -- verify (read-only) ------------------------------------------------------------------------

    async def _exists(self, deployment_id: str, spec: ResourceSpec) -> bool:
        if spec.disposition == "reuse":
            row = await self._register.get_row(deployment_id, spec.resource_id or "")
            return row is not None and row.ownership is not Ownership.CREATED
        if spec.kind == "arm_resource":
            assert self._arm is not None
            return await self._arm.exists(spec)
        assert self._observer is not None
        if spec.kind == "fabric_capacity":
            return await self._observer.capacity_exists(spec)
        return await self._observer.workspace_exists(spec)

    # -- uninstall (dry run only) ----------------------------------------------------------------

    @staticmethod
    def _deployment(request: WriteRequest) -> str:
        return _split_target(request.target, DEPLOYMENT_ENTITY)[2]

    async def _uninstall_dry_run(self, request: WriteRequest) -> DryRunResult:
        cloud, _customer, deployment_id = _split_target(request.target, DEPLOYMENT_ENTITY)
        if cloud != self._cloud.value:
            raise ForbiddenError("the deployment is in another cloud", reason=CLOUD_MISMATCH)
        rows = await self._register.list_rows(deployment_id)
        digest = register_digest(rows)
        if request.target_version != digest:
            raise StaleVersionError("the register changed", reason=TARGET_VERSION_CHANGED)
        plan = await uninstall_preview(deployment_id, rows, self._inventory)
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=uninstall_diff(digest, _removable_ids(plan.removable)),
            would_change=False,  # a preview never changes anything
        )


def _removable_ids(entries: Collection[Any]) -> list[str]:
    return [e.resource_id for e in entries]


def _unavailable(detail: str) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(CAPABILITY_UNAVAILABLE, detail)
