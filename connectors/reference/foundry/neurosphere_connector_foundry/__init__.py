"""Reference Foundry discovery connector (PRP-09 item 5)."""

from neurosphere_connector_foundry.capabilities import (
    CapabilityReport,
    CapabilityStatus,
    capability_reports,
)
from neurosphere_connector_foundry.connector import (
    DiscoveredAgent,
    DiscoveredDeployment,
    DiscoveryResult,
    FoundryDiscoveryConnector,
)
from neurosphere_connector_foundry.endpoints import FOUNDRY_ENDPOINTS, project_endpoint
from neurosphere_connector_foundry.reader import FoundryProjectReader, SdkProjectReader

__all__ = [
    "FOUNDRY_ENDPOINTS",
    "CapabilityReport",
    "CapabilityStatus",
    "DiscoveredAgent",
    "DiscoveredDeployment",
    "DiscoveryResult",
    "FoundryDiscoveryConnector",
    "FoundryProjectReader",
    "SdkProjectReader",
    "capability_reports",
    "project_endpoint",
]
