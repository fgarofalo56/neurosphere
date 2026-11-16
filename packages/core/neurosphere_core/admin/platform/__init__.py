"""Platform configuration administration (PRP-44): domains, budgets, price sheets, review policy.

Core rules over the ``admin_config`` store (PRP-65) and the append-only ``price_snapshots`` store.
The API routes (``neurosphere_api.admin.platform``) and the worker pickup
(``neurosphere_workers.admin_platform``) both call these.
"""

from __future__ import annotations

from dataclasses import dataclass

from neurosphere_core.admin.platform.budgets import BUDGET_KIND, BudgetAdmin
from neurosphere_core.admin.platform.domains import (
    DOMAIN_KIND,
    RESERVED_DOMAIN_NAMES,
    DomainAdmin,
    DomainRegistry,
    DomainWrite,
)
from neurosphere_core.admin.platform.price_sheet import (
    CoverageReport,
    IncompleteModel,
    PriceSheetAdmin,
    PriceSheetResult,
    coverage_report,
    price_sheet_to_snapshot,
)
from neurosphere_core.admin.platform.price_table import (
    PriceVersionConflictError,
    merge_price_tables,
)
from neurosphere_core.admin.platform.review_policy import (
    REVIEW_POLICY_ID,
    REVIEW_POLICY_KIND,
    LoadableReviewPolicyRegistry,
    PolicyAlreadyLoadedError,
    PolicyChange,
    StoredPolicies,
    defaults_document,
    diff_documents,
    policies_from_document,
    validate_review_policy,
)
from neurosphere_core.admin.platform.review_policy_admin import (
    DEFAULTS_ETAG,
    ReviewPolicyAdmin,
    ReviewPolicyRead,
    ReviewPolicyWrite,
)

__all__ = [
    "BUDGET_KIND",
    "DEFAULTS_ETAG",
    "DOMAIN_KIND",
    "RESERVED_DOMAIN_NAMES",
    "REVIEW_POLICY_ID",
    "REVIEW_POLICY_KIND",
    "BudgetAdmin",
    "CoverageReport",
    "DomainAdmin",
    "DomainRegistry",
    "DomainWrite",
    "IncompleteModel",
    "LoadableReviewPolicyRegistry",
    "PlatformAdmin",
    "PolicyAlreadyLoadedError",
    "PolicyChange",
    "PriceSheetAdmin",
    "PriceSheetResult",
    "PriceVersionConflictError",
    "ReviewPolicyAdmin",
    "ReviewPolicyRead",
    "ReviewPolicyWrite",
    "StoredPolicies",
    "coverage_report",
    "defaults_document",
    "diff_documents",
    "merge_price_tables",
    "policies_from_document",
    "price_sheet_to_snapshot",
    "validate_review_policy",
]


@dataclass(frozen=True, slots=True)
class PlatformAdmin:
    """The four administration services the API plane carries."""

    domains: DomainAdmin
    registry: DomainRegistry
    budgets: BudgetAdmin
    price_sheets: PriceSheetAdmin
    review_policy: ReviewPolicyAdmin
