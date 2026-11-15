"""Operator control-plane storage (PRP-65): the versioned ``admin_config`` store.

Every control-plane PRP (PRP-41 producers, 42 connectors, 44 domains/budgets/prices/review
policy, 45 system settings) stores its documents here instead of inventing a store. Policy
(identity) writes are NOT here: they live in ``neurosphere_core.auth.scope.policy_admin`` and use
the existing ``policy`` container so derivation reads them unchanged.
"""

from neurosphere_core.admin.chains import ADMIN_CONFIG_CHAIN_SUFFIX, admin_config_chain_id
from neurosphere_core.admin.cosmos_store import (
    ADMIN_CONFIG_DOC_TYPE,
    CosmosAdminConfigRepository,
    cosmos_item_id,
    create_admin_config_container,
)
from neurosphere_core.admin.models import (
    ADMIN_CONFIG_CONTAINER,
    ADMIN_CONFIG_PARTITION_KEY_PATH,
    ADMIN_CONFIG_SCHEMA_VERSION,
    ADMIN_KIND_MODELS,
    ADMIN_KINDS,
    AdminBody,
    AdminKindName,
    validate_admin_body,
    validate_kind,
)
from neurosphere_core.admin.store import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    AdminConfigRepository,
    AdminConfigStoreBase,
    InMemoryAdminConfigRepository,
)

__all__ = [
    "ADMIN_CONFIG_CHAIN_SUFFIX",
    "ADMIN_CONFIG_CONTAINER",
    "ADMIN_CONFIG_DOC_TYPE",
    "ADMIN_CONFIG_PARTITION_KEY_PATH",
    "ADMIN_CONFIG_SCHEMA_VERSION",
    "ADMIN_KINDS",
    "ADMIN_KIND_MODELS",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "AdminBody",
    "AdminConfigRepository",
    "AdminConfigStoreBase",
    "AdminKindName",
    "CosmosAdminConfigRepository",
    "InMemoryAdminConfigRepository",
    "admin_config_chain_id",
    "cosmos_item_id",
    "create_admin_config_container",
    "validate_admin_body",
    "validate_kind",
]
