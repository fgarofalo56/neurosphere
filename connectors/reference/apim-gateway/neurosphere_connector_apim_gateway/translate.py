"""From a ``WriteRequest`` to resource specs: the per-target-kind seam.

Each target kind (``entity_type``) has one ``IntentTranslator``. This module ships the generic
one for target ``apim_gateway`` (the gateway itself; the diff names whole resources). Later
PRP-34 items add translators in their own modules (``apim_backend`` for model swaps, ``grant``
for caps and publication, ``mcp_server``) and register them with the connector, without editing
the planner or applier.

Plan binding: the reviewed plan digest travels INSIDE the proposed diff as an RFC 6902 ``test``
operation at ``/plan_digest``. The diff is part of the confirmation hash (PRP-17 D1), so the
approver's confirmation binds the exact plan; ``dry_run`` returns the diff with that operation
added, and ``apply`` refuses a request without it or whose re-planned digest differs.

Generic diff grammar (target ``apim_gateway``): ``add``/``replace`` at ``/resources/{path}``
upserts the resource whose relative ARM path is ``{path}`` (``/`` escaped as ``~1``) with the
operation value as its ``properties`` object; ``remove`` at the same pointer deletes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

from neurosphere_connector_apim_gateway.arm import ApimArm, check_path
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.models import ResourceSpec

__all__ = [
    "GATEWAY_ENTITY_TYPE",
    "PLAN_DIGEST_PATH",
    "GatewayResourcesTranslator",
    "IntentTranslator",
    "escape_token",
    "resource_pointer",
    "reviewed_digest",
    "with_digest",
]

PLAN_DIGEST_PATH: Final = "/plan_digest"
GATEWAY_ENTITY_TYPE: Final = "apim_gateway"
_RESOURCES: Final = "/resources/"


def escape_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resource_pointer(name: str) -> str:
    return _RESOURCES + escape_token(name)


@runtime_checkable
class IntentTranslator(Protocol):
    @property
    def entity_types(self) -> frozenset[str]: ...

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        """The live version ``request.target_version`` is compared with (an ETag)."""
        ...

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        """Desired resource states; pure, no I/O."""
        ...


def reviewed_digest(diff: ProposedDiff) -> str | None:
    found = [op for op in diff.operations if op.path == PLAN_DIGEST_PATH]
    if not found:
        return None
    if len(found) > 1 or found[0].op != "test" or not isinstance(found[0].value, str):
        raise InvalidSchemaError("plan digest must be one test operation", reason="bad_plan_digest")
    return found[0].value


def with_digest(diff: ProposedDiff, digest: str) -> ProposedDiff:
    """The diff with exactly one leading ``test /plan_digest`` operation."""
    rest = [op for op in diff.operations if op.path != PLAN_DIGEST_PATH]
    head = PatchOperation(op="test", path=PLAN_DIGEST_PATH, value=digest)
    return ProposedDiff(format="json_patch", operations=[head, *rest])


def _target_gateway(gateway: GatewayRef, request: WriteRequest) -> None:
    cloud, _, rest = request.target.canonical_id.partition(":")
    if cloud != gateway.cloud.value:
        raise InvalidSchemaError("target cloud differs from connector", reason="cloud_mismatch")
    if rest.rsplit(":", 1)[-1] != gateway.gateway_id:
        raise InvalidSchemaError("target is not this gateway", reason="wrong_entity")


class GatewayResourcesTranslator:
    """Target ``apim_gateway``: the diff names whole resources; version is the service ETag."""

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({GATEWAY_ENTITY_TYPE})

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        _target_gateway(gateway, request)
        service = await arm.get("")
        if service is None or not service.etag:
            raise CapabilityUnavailableError(
                "gateway_not_readable", "the APIM service has no readable ETag"
            )
        return service.etag

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        _target_gateway(gateway, request)
        specs: list[ResourceSpec] = []
        for op in request.proposed_diff.operations:
            if op.path == PLAN_DIGEST_PATH:
                continue
            specs.append(_spec(op))
        if not specs:
            raise InvalidSchemaError("the diff names no resource", reason="empty_plan")
        return specs


def _spec(op: PatchOperation) -> ResourceSpec:
    if not op.path.startswith(_RESOURCES) or "/" in op.path[len(_RESOURCES) :]:
        raise InvalidSchemaError("unsupported diff path", reason="unsupported_operation")
    name = _unescape(op.path[len(_RESOURCES) :])
    rtype = check_path(name)
    if rtype is None:  # pragma: no cover - check_path refuses the service path here
        raise InvalidSchemaError("not a child resource", reason="bad_path")
    if op.op == "remove":
        return ResourceSpec(resource_type=rtype, name=name, operation="delete")
    if op.op not in ("add", "replace"):
        raise InvalidSchemaError("unsupported diff operation", reason="unsupported_operation")
    if not isinstance(op.value, Mapping):
        raise InvalidSchemaError("resource value must be a properties object", reason="bad_payload")
    payload: dict[str, Any] = {str(k): v for k, v in op.value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return ResourceSpec(resource_type=rtype, name=name, operation="upsert", payload=payload)
