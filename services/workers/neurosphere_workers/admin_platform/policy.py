"""Load the stored review policy for a worker role (PRP-44 item 5)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

from neurosphere_core.admin import CosmosAdminConfigRepository
from neurosphere_core.admin.platform import LoadableReviewPolicyRegistry

if TYPE_CHECKING:
    from neurosphere_workers.runtime.factories import RuntimeConfig

__all__ = ["POLICY_STORE_UNAVAILABLE", "load_review_policies"]

POLICY_STORE_UNAVAILABLE: Final = "review_policy_store_unavailable"
_TIMEOUT_SECONDS: Final = 10.0
_log = logging.getLogger("neurosphere_workers.admin_platform")


async def load_review_policies(
    cfg: RuntimeConfig, cosmos: Any, *, timeout_seconds: float = _TIMEOUT_SECONDS
) -> LoadableReviewPolicyRegistry:
    """A registry with the stored policy applied; the built-in defaults when none is stored or the
    read fails (one log line, reason code only)."""
    registry = LoadableReviewPolicyRegistry()
    customer = cfg.auth.resolved_customer_id(cfg.settings.env)
    if customer is None:
        registry.load(None)
        return registry
    repository = CosmosAdminConfigRepository.from_client(
        cosmos,
        database=cfg.store.database,
        cloud=cfg.cloud,  # type: ignore[arg-type]
    )
    try:
        applied = await asyncio.wait_for(registry.load_from(repository, customer), timeout_seconds)
    except Exception:
        _log.warning(
            "stored review policy unavailable; using the defaults",
            extra={
                "event": "worker.review_policy_store_unavailable",
                "reason": POLICY_STORE_UNAVAILABLE,
            },
        )
        registry.load(None)
        return registry
    _log.info(
        "review policy resolved",
        extra={"event": "worker.review_policy_resolved", "stored": applied},
    )
    return registry
