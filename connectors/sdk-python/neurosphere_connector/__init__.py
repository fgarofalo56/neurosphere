"""NeuroSphere connector SDK (PRP-09): base connector, manifest, health, vault credentials, kit.

``neurosphere_connector.write`` (PRP-09 item 6) is added separately and is not imported here.
"""

from neurosphere_connector.connector import BaseConnector
from neurosphere_connector.contract_kit import Violation, check_connector_contract
from neurosphere_connector.health import (
    CoverageReport,
    FreshnessReport,
    HealthReport,
    HealthState,
    HealthTracker,
    RateLimitStatus,
)
from neurosphere_connector.manifest import build_manifest, manifest_issues, validate_manifest
from neurosphere_connector.vault import (
    CredentialBroker,
    CredentialResolver,
    RotationSource,
    SecretValue,
    StaticCredentialResolver,
)

__all__ = [
    "BaseConnector",
    "CoverageReport",
    "CredentialBroker",
    "CredentialResolver",
    "FreshnessReport",
    "HealthReport",
    "HealthState",
    "HealthTracker",
    "RateLimitStatus",
    "RotationSource",
    "SecretValue",
    "StaticCredentialResolver",
    "Violation",
    "build_manifest",
    "check_connector_contract",
    "manifest_issues",
    "validate_manifest",
]
