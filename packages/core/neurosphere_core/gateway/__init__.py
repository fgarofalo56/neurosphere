"""APIM gateway registry (PRP-33 item 6): observe-mode registration, preflight and inventory.

Read-only against the customer's gateway: see :mod:`neurosphere_core.gateway.inventory`.
PRP-34 item 2 adds the observe/manage mode and its write-permission preflight
(:mod:`neurosphere_core.gateway.mode`) and the durable append-only apply-record store
(:mod:`neurosphere_core.gateway.records`).
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
    GatewayMode,
    GatewayRegistration,
    ModePreflight,
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
from neurosphere_core.gateway.records import (
    CosmosGatewayRecordStore,
    InMemoryGatewayRecordStore,
)
from neurosphere_core.gateway.store import GatewayModeLookup, GatewayStore, InMemoryGatewayStore

__all__ = [
    "DEFAULT_GATEWAY_CONTAINER",
    "ApiEntry",
    "BackendEntry",
    "CircuitBreakerRule",
    "CosmosGatewayRecordStore",
    "CosmosGatewayStore",
    "DiagnosticsState",
    "GatewayInventory",
    "GatewayMode",
    "GatewayModeLookup",
    "GatewayRegistration",
    "GatewayStore",
    "InMemoryGatewayRecordStore",
    "InMemoryGatewayStore",
    "ModePreflight",
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
