"""Configuration detections and shadow-AI discovery (PRP-61).

Rules over reader protocols; findings become stored recommendations of kind
``configuration_finding`` or ``unregistered_ai_resource``. Metadata only, read only.
"""

from neurosphere_core.detections.mapper import (
    finding_recommendation_id,
    finding_to_recommendation,
    read_unavailable,
)
from neurosphere_core.detections.models import (
    CROSS_CLOUD_REASON,
    KIND_CONFIGURATION_FINDING,
    KIND_UNREGISTERED_AI_RESOURCE,
    RULE_CONTENT_FILTER,
    RULE_CONTENT_FILTER_UNSET_ONLY,
    RULE_GATEWAY_FRAGMENT,
    RULE_SHADOW_AI,
    RULE_VERSION,
    AccountRead,
    AiAccount,
    AiAccountInventory,
    CatalogDeploymentReader,
    CatalogRead,
    CoverageStatus,
    DeploymentConfig,
    DeploymentConfigRead,
    DeploymentConfigReader,
    DetectionRule,
    Finding,
    GatewayFragments,
    GatewayInventoryReader,
    GatewayRead,
    ReadStatus,
    RuleResult,
)
from neurosphere_core.detections.rules import ContentFilterRule, GatewayFragmentRule, ShadowAiRule

__all__ = [
    "CROSS_CLOUD_REASON",
    "KIND_CONFIGURATION_FINDING",
    "KIND_UNREGISTERED_AI_RESOURCE",
    "RULE_CONTENT_FILTER",
    "RULE_CONTENT_FILTER_UNSET_ONLY",
    "RULE_GATEWAY_FRAGMENT",
    "RULE_SHADOW_AI",
    "RULE_VERSION",
    "AccountRead",
    "AiAccount",
    "AiAccountInventory",
    "CatalogDeploymentReader",
    "CatalogRead",
    "ContentFilterRule",
    "CoverageStatus",
    "DeploymentConfig",
    "DeploymentConfigRead",
    "DeploymentConfigReader",
    "DetectionRule",
    "Finding",
    "GatewayFragmentRule",
    "GatewayFragments",
    "GatewayInventoryReader",
    "GatewayRead",
    "ReadStatus",
    "RuleResult",
    "ShadowAiRule",
    "finding_recommendation_id",
    "finding_to_recommendation",
    "read_unavailable",
]
