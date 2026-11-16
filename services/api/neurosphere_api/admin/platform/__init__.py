"""Platform configuration admin API (PRP-44), mounted at ``/api/v1/admin/platform``.

Four areas, each an audited ``If-Match`` API behind customer-level ``config.manage``:

* ``domains``: the domain registry (create, list, retire);
* ``budgets``: stored spend budgets with alert thresholds (nothing evaluates them);
* ``price-sheets``: append-only versioned price sheets feeding the ingestion cost ledger;
* ``review-policy``: the stored human-review policy (maker-checker can never be loosened).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from neurosphere_api.admin.platform.service import (
    STATE_ATTRIBUTE,
    PlatformAdminPlane,
    configure_admin_platform,
)

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = [
    "PREFIX",
    "STATE_ATTRIBUTE",
    "PlatformAdminPlane",
    "configure_admin_platform",
    "register",
]

PREFIX: Final = "/api/v1/admin/platform"


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (``neurosphere_api/routers.py``)."""
    from neurosphere_api.admin.platform import budgets, domains, price_sheets, review_policy

    registry.register(f"{PREFIX}/domains", domains.build_router())
    registry.register(f"{PREFIX}/budgets", budgets.build_router())
    registry.register(f"{PREFIX}/price-sheets", price_sheets.build_router())
    registry.register(f"{PREFIX}/review-policy", review_policy.build_router())
