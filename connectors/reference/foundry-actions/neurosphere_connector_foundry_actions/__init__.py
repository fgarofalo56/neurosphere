"""Foundry model-deployment swap write connector (PRP-17 item 5)."""

from neurosphere_connector_foundry_actions.arm import ArmClient
from neurosphere_connector_foundry_actions.connector import (
    ADVISORY_CONNECTOR_NAME,
    CONNECTOR_NAME,
    FoundryModelSwapAdvisoryConnector,
    FoundryModelSwapConnector,
    create_swap_connector,
)
from neurosphere_connector_foundry_actions.endpoints import (
    ARM_ENDPOINTS,
    DEPLOYMENTS_API_VERSION,
    MODELS_API_VERSION,
    PERMISSIONS_API_VERSION,
    AccountRef,
)
from neurosphere_connector_foundry_actions.logic import CompatCheck

__all__ = [
    "ADVISORY_CONNECTOR_NAME",
    "ARM_ENDPOINTS",
    "CONNECTOR_NAME",
    "DEPLOYMENTS_API_VERSION",
    "MODELS_API_VERSION",
    "PERMISSIONS_API_VERSION",
    "AccountRef",
    "ArmClient",
    "CompatCheck",
    "FoundryModelSwapAdvisoryConnector",
    "FoundryModelSwapConnector",
    "create_swap_connector",
]
