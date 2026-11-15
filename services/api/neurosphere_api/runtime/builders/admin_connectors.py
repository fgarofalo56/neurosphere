"""Connector admin builder (PRP-42 item 4): installs ``app.state.admin_connectors``.

Component ``admin_connectors`` is OPTIONAL: a deployment without it still serves, and the routes
answer 503 ``admin_connectors_unconfigured``. It reports ``disabled`` (reason code logged) when
the Cosmos client is not available. The audit repository is read per request: without it every
mutation fails closed (503 ``audit_store_unconfigured``).

* Store: ``backend("admin_config_repository")`` (an ``AdminConfigRepository``) wins; else the
  ``CosmosAdminConfigRepository`` on the ONE shared Cosmos client, container ``admin_config``,
  bound to the deployment cloud (a stateless wrapper; PRP-41 builds its own over the same client).
* Validators: the worker package's per-kind validators, so the API refuses what the worker would.
* Audit: the ``AUDIT_REPOSITORY`` the data builder published (resolved lazily); chain
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
from neurosphere_core.admin.connectors import ConnectorConfigAdmin
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_workers.connector_config import VALIDATORS

from neurosphere_api.admin.sources.connectors.service import (
    ConnectorAdminPlane,
    configure_admin_connectors,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("admin_connectors",)

_log = logging.getLogger("neurosphere_api.runtime")


def _repository(ctx: BuildContext) -> AdminConfigRepository:
    cloud = ctx.settings.cloud_profile.cloud.value
    override = ctx.overrides.backend("admin_config_repository")
    if override is not None:
        if not isinstance(override, AdminConfigRepository):
            raise ComponentUnavailableError("admin_config_override_invalid")
        return override
    if isinstance(ctx.overrides.policy_repository, InMemoryPolicyRepository):
        # Tests and the local sandbox composed on an in-memory policy store: same for this one.
        return InMemoryAdminConfigRepository(cloud=cloud)  # type: ignore[arg-type]
    return CosmosAdminConfigRepository.from_client(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        cloud=cloud,  # type: ignore[arg-type]
    )


def _plane(ctx: BuildContext) -> ConnectorAdminPlane:
    admin = ConnectorConfigAdmin(
        _repository(ctx),
        cloud=ctx.settings.cloud_profile.cloud.value,  # type: ignore[arg-type]
        validators=VALIDATORS,
    )
    return ConnectorAdminPlane(admin=admin, audit=lambda: ctx.maybe_shared(AUDIT_REPOSITORY))


def build(ctx: BuildContext) -> None:
    configure_admin_connectors(ctx.app, None)
    try:
        plane = _plane(ctx)
    except ComponentUnavailableError as exc:
        _log.warning("component admin_connectors disabled: %s", exc.reason)
        ctx.disabled("admin_connectors")
        return
    configure_admin_connectors(ctx.app, plane)
    ctx.ok("admin_connectors")


BUILDER: Final = BuilderSpec("admin_connectors", COMPONENTS, build)
