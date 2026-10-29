"""APIM gateway registry (PRP-33 item 6): observe-mode registration, preflight and inventory.

Read-only against the customer's gateway: see :mod:`neurosphere_core.gateway.inventory`.
"""

from neurosphere_core.gateway.cosmos_store import (
    DEFAULT_GATEWAY_CONTAINER,
    CosmosGatewayStore,
    create_gateway_container,
)
from neurosphere_core.gateway.inventory import PreflightResult, preflight, read_inventory
from neurosphere_core.gateway.models import (
    ApiEntry,
    BackendEntry,
    CircuitBreakerRule,
    DiagnosticsState,
    GatewayInventory,
    GatewayRegistration,
    OperationEntry,
    PolicyFragmentEntry,
    PoolMember,
    ProductApiLink,
    ProductEntry,
    SubscriptionEntry,
    Tier,
    gateway_id_for,
    normalize_arm_id,
)
from neurosphere_core.gateway.store import GatewayStore, InMemoryGatewayStore

__all__ = [
    "DEFAULT_GATEWAY_CONTAINER",
    "ApiEntry",
    "BackendEntry",
    "CircuitBreakerRule",
    "CosmosGatewayStore",
    "DiagnosticsState",
    "GatewayInventory",
    "GatewayRegistration",
    "GatewayStore",
    "InMemoryGatewayStore",
    "OperationEntry",
    "PolicyFragmentEntry",
    "PoolMember",
    "PreflightResult",
    "ProductApiLink",
    "ProductEntry",
    "SubscriptionEntry",
    "Tier",
    "create_gateway_container",
    "gateway_id_for",
    "normalize_arm_id",
    "preflight",
    "read_inventory",
]
