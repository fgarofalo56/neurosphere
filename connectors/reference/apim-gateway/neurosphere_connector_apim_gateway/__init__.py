"""APIM AI gateway write connector (PRP-34).

Module layout, so later items extend without editing shared files:

- ``models``: plan, step, apply-record models and the dependency order.
- ``planner`` / ``applier``: build a digest-bound plan; apply it with ownership and reverse it.
- ``arm``: the ``ApimArm`` protocol and its REST implementation over PRP-33's ARM client.
- ``inmemory``: the in-memory APIM test double (ARM resource tree with ETags).
- ``records``: the append-only apply-record store protocol and in-memory store.
- ``translate``: the per-target-kind ``IntentTranslator`` seam (items 3-6 add translators).
- ``policies``: policy XML templates and renderers.
- ``connector``: the ``WriteConnector`` and the advisory connector.
- ``mode``: the ``gateway_mode_change`` step (permissions preflight, observe/manage flip).
"""

from neurosphere_connector_apim_gateway.applier import PlanApplier, RollbackFailedError
from neurosphere_connector_apim_gateway.arm import (
    APIM_API_VERSION,
    PERMISSIONS_PATH,
    ApimArm,
    ApimPermissionsReader,
    ArmResource,
    HttpApimArm,
)
from neurosphere_connector_apim_gateway.connector import (
    ACTION_KINDS,
    ADVISORY_CONNECTOR_NAME,
    CONNECTOR_NAME,
    ApimGatewayAdvisoryConnector,
    ApimGatewayConnector,
    create_apim_connector,
    manifest_actions,
)
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.inmemory import InMemoryApim
from neurosphere_connector_apim_gateway.mode import MODE_TARGET_TYPE, GatewayModeHandler
from neurosphere_connector_apim_gateway.models import (
    DEPENDENCY_ORDER,
    ApplyRecord,
    PlanStep,
    PublishPlan,
    ResourceSpec,
    ResourceType,
    StepOwnership,
    StepRecord,
)
from neurosphere_connector_apim_gateway.planner import build_plan
from neurosphere_connector_apim_gateway.records import ApplyRecordStore, InMemoryApplyRecordStore
from neurosphere_connector_apim_gateway.translate import (
    GATEWAY_ENTITY_TYPE,
    PLAN_DIGEST_PATH,
    GatewayResourcesTranslator,
    IntentTranslator,
    resource_pointer,
)

__all__ = [
    "ACTION_KINDS",
    "ADVISORY_CONNECTOR_NAME",
    "APIM_API_VERSION",
    "CONNECTOR_NAME",
    "DEPENDENCY_ORDER",
    "GATEWAY_ENTITY_TYPE",
    "MODE_TARGET_TYPE",
    "PERMISSIONS_PATH",
    "PLAN_DIGEST_PATH",
    "ApimArm",
    "ApimGatewayAdvisoryConnector",
    "ApimGatewayConnector",
    "ApimPermissionsReader",
    "ApplyRecord",
    "ApplyRecordStore",
    "ArmResource",
    "GatewayModeHandler",
    "GatewayRef",
    "GatewayResourcesTranslator",
    "HttpApimArm",
    "InMemoryApim",
    "InMemoryApplyRecordStore",
    "IntentTranslator",
    "PlanApplier",
    "PlanStep",
    "PublishPlan",
    "ResourceSpec",
    "ResourceType",
    "RollbackFailedError",
    "StepOwnership",
    "StepRecord",
    "build_plan",
    "create_apim_connector",
    "manifest_actions",
    "resource_pointer",
]
