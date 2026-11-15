"""Lifecycle API state (PRP-23 round 2 item 3).

Installs :class:`~neurosphere_api.lifecycle.LifecycleApiState` on ``app.state.lifecycle``: the
Cosmos job store, hold registry and request queue (``lifecycle_requests`` and ``lifecycle_holds``
containers, bound to the deployment's customer), the shared audit repository, the retention
policy read from ``NS_LIFECYCLE_POLICY_FILE`` and the mode from ``NS_LIFECYCLE_MODE``.

It reports no readiness component (the lifecycle API is an operator surface, not a platform
dependency): when it cannot be built the routes answer 503 ``lifecycle_unconfigured`` and the
reason is logged. Test seam: ``ctx.overrides.backend("lifecycle_state")`` (a ready
``LifecycleApiState``).
"""

from __future__ import annotations

import logging
from typing import Final

from neurosphere_core.lifecycle.cosmos import CosmosHoldRegistry, CosmosRequestQueue
from neurosphere_core.lifecycle.jobs import CosmosJobStore
from neurosphere_core.lifecycle.policy import load_policy_file
from neurosphere_core.lifecycle.settings import LifecycleSettings
from pydantic import ValidationError

from neurosphere_api.lifecycle import STATE_ATTRIBUTE, LifecycleApiState
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ()
_SEAM: Final = "lifecycle_state"
_log = logging.getLogger("neurosphere_api.runtime")


def _build(ctx: BuildContext) -> LifecycleApiState:
    try:
        settings = LifecycleSettings()
    except ValidationError:
        raise ComponentUnavailableError("lifecycle_settings_invalid") from None
    audit = ctx.maybe_shared(AUDIT_REPOSITORY)
    if audit is None:
        raise ComponentUnavailableError("audit_unavailable")
    customer = ctx.auth_settings().resolved_customer_id(ctx.settings.env)
    if customer is None:
        raise ComponentUnavailableError("customer_unconfigured")
    client = ctx.cosmos_client()
    database = ctx.store_settings().database
    return LifecycleApiState(
        jobs=CosmosJobStore.from_client(client, database=database, customer_id=customer),
        holds=CosmosHoldRegistry.from_client(client, database=database, customer_id=customer),
        queue=CosmosRequestQueue.from_client(client, database=database, customer_id=customer),
        audit=audit,
        mode=settings.mode,
        policy=load_policy_file(settings.policy_file),
    )


def build(ctx: BuildContext) -> None:
    seam = ctx.overrides.backend(_SEAM)
    if isinstance(seam, LifecycleApiState):
        setattr(ctx.app.state, STATE_ATTRIBUTE, seam)
        return
    try:
        state = _build(ctx)
    except ComponentUnavailableError as exc:
        _log.warning("lifecycle API not installed: %s", exc.reason)
        return
    setattr(ctx.app.state, STATE_ATTRIBUTE, state)


BUILDER: Final = BuilderSpec("lifecycle", COMPONENTS, build)
