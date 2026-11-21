"""Source status builder (PRP-139 item 3): installs ``app.state.source_status``.

Component ``sources_status`` is OPTIONAL: a deployment without it still serves and the two routes
answer 503 ``source_status_unconfigured``. It reports ``disabled`` (reason code logged) when the
Cosmos client is not available.

* Run statuses: ``backend("source_status_repository")`` (a ``SourceStatusRepository``) wins; with
  an in-memory policy store (tests, local sandbox) an in-memory twin; else the Cosmos repository
  on the ONE shared client, container ``admin_config`` (record kind ``connector_run_status``).
* Connector configurations (kind and enabled flag only): ``backend("admin_config_repository")``
  or the same store ``admin_connectors`` uses.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Final

from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.admin import (
    AdminConfigRepository,
    CosmosAdminConfigRepository,
    InMemoryAdminConfigRepository,
)
from neurosphere_core.auth.scope import InMemoryPolicyRepository
from neurosphere_core.sources_status import (
    ConfiguredConnector,
    CosmosSourceStatusRepository,
    InMemorySourceStatusRepository,
    SourceStatusRepository,
)

from neurosphere_api.runtime.builders import (
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.sources_status import SourceStatusPlane, configure_source_status
from neurosphere_api.sources_status.service import ConfigLister

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("sources_status",)
_CONNECTOR_KIND: Final = "connector_config"
_MAX_CONFIGS: Final = 200

_log = logging.getLogger("neurosphere_api.runtime")


def _statuses(ctx: BuildContext) -> SourceStatusRepository:
    override = ctx.overrides.backend("source_status_repository")
    if override is not None:
        if not isinstance(override, SourceStatusRepository):
            raise ComponentUnavailableError("source_status_override_invalid")
        return override
    if isinstance(ctx.overrides.policy_repository, InMemoryPolicyRepository):
        return InMemorySourceStatusRepository()
    return CosmosSourceStatusRepository.from_client(
        ctx.cosmos_client(), database=ctx.store_settings().database
    )


def _config_repository(ctx: BuildContext) -> AdminConfigRepository:
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


def _lister(repository: AdminConfigRepository) -> ConfigLister:
    async def configs(customer_id: str) -> Sequence[ConfiguredConnector]:
        documents = await repository.list_by_kind(customer_id, _CONNECTOR_KIND, limit=_MAX_CONFIGS)
        return [
            ConfiguredConnector(kind=d.body.connector_kind, enabled=d.body.enabled)
            for d in documents
            if isinstance(d.body, ConnectorConfig)
        ]

    return configs


def build(ctx: BuildContext) -> None:
    configure_source_status(ctx.app, None)
    try:
        plane = SourceStatusPlane(statuses=_statuses(ctx), configs=_lister(_config_repository(ctx)))
    except ComponentUnavailableError as exc:
        _log.warning("component sources_status disabled: %s", exc.reason)
        ctx.disabled("sources_status")
        return
    configure_source_status(ctx.app, plane)
    ctx.ok("sources_status")


BUILDER: Final = BuilderSpec("sources_status", COMPONENTS, build)
