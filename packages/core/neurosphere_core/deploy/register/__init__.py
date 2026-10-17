"""Ownership and dependency register with a guarded removal path (PRP-08 item 5).

``CosmosRegisterStore`` lives in ``neurosphere_core.deploy.register.cosmos_store`` and is
imported explicitly by callers that wire Cosmos.
"""

from neurosphere_core.deploy.register.consent import (
    ConsentAuditSink,
    NoOpConsentAuditSink,
    record_consent,
)
from neurosphere_core.deploy.register.guard import (
    Action,
    LiveInventory,
    PlanEntry,
    RemovalPlan,
    ResourceDeleter,
    assert_removable,
    assert_resource_group_empty_of_foreign,
    plan_removal,
    remove,
)
from neurosphere_core.deploy.register.models import (
    ConsentRecord,
    Ownership,
    RegisterExport,
    ResourceRow,
    normalize_id,
)
from neurosphere_core.deploy.register.store import InMemoryRegisterStore, RegisterStore

__all__ = [
    "Action",
    "ConsentAuditSink",
    "ConsentRecord",
    "InMemoryRegisterStore",
    "LiveInventory",
    "NoOpConsentAuditSink",
    "Ownership",
    "PlanEntry",
    "RegisterExport",
    "RegisterStore",
    "RemovalPlan",
    "ResourceDeleter",
    "ResourceRow",
    "assert_removable",
    "assert_resource_group_empty_of_foreign",
    "normalize_id",
    "plan_removal",
    "record_consent",
    "remove",
]
