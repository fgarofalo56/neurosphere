"""System admin builder (PRP-45 item 4): installs ``app.state.admin_system``.

Component ``admin_system`` is OPTIONAL: without it the ``/api/v1/admin/system/*`` routes answer
503 ``admin_system_unconfigured`` and everything else serves. It reports ``disabled`` (reason code
logged) when no ``admin_config`` store can be built (no Cosmos client).

* Store: ``backend("admin_config_repository")`` wins; an in-memory policy store (tests, local
  sandbox) gets an in-memory twin; else ``CosmosAdminConfigRepository`` on the ONE shared client.
* Applied settings: the snapshot ``compose_app`` loaded before any builder ran
  (``STORED_SETTINGS``); absent means env only.
* Audit: the ``AUDIT_REPOSITORY`` the data builder published (resolved per request); chain
  ``<customer>.admin-config``.
"""

from __future__ import annotations

import logging
from typing import Final

from neurosphere_core.admin import (
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
)
from neurosphere_core.admin.runtime import STORED_SETTINGS_UNCONFIGURED, StoredSettingsSnapshot
from neurosphere_core.auth.scope import InMemoryPolicyRepository

from neurosphere_api.admin.system.service import SystemAdminPlane, configure_admin_system
from neurosphere_api.admin.system.stored import STORED_SETTINGS
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("admin_system",)

_log = logging.getLogger("neurosphere_api.runtime")


def _repository(ctx: BuildContext) -> AdminConfigRepository:
    cloud = ctx.settings.cloud_profile.cloud.value
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return override
    if isinstance(ctx.overrides.policy_repository, InMemoryPolicyRepository):
        return InMemoryAdminConfigRepository(cloud=cloud)  # type: ignore[arg-type]
    return CosmosAdminConfigRepository.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        cloud=cloud,  # type: ignore[arg-type]
    )


def _customer_binding(ctx: BuildContext) -> str:
    try:
        auth = ctx.auth_settings()
    except ComponentUnavailableError:
        return "missing"
    if auth.customer_id is not None:
        return "explicit"
    return "local_default" if ctx.settings.env == "local" else "missing"


def build(ctx: BuildContext) -> None:
    configure_admin_system(ctx.app, None)
    snapshot = ctx.maybe_shared(STORED_SETTINGS) or StoredSettingsSnapshot.empty(
        "unconfigured", STORED_SETTINGS_UNCONFIGURED
    )
    try:
        repository = _repository(ctx)
    except ComponentUnavailableError as exc:
        _log.warning("component admin_system disabled: %s", exc.reason)
        ctx.disabled("admin_system")
        return
    plane = SystemAdminPlane(
        repository=repository,
        audit=lambda: ctx.maybe_shared(AUDIT_REPOSITORY),
        applied=snapshot,
        cloud=ctx.settings.cloud_profile.cloud.value,
        environ=dict(ctx.environ),
        customer_binding=_customer_binding(ctx),
    )
    configure_admin_system(ctx.app, plane)
    ctx.ok("admin_system")


BUILDER: Final = BuilderSpec("admin_system", COMPONENTS, build)
