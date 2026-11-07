"""Opt-in construction of the apply/uninstall-preview collaborators (called from ``main.create``).

``NS_DEPLOY_APPLY_ENABLED`` unset/false: nothing is configured and every
``/api/v1/deploy/apply`` route keeps failing closed with 503 (``apply_not_configured``), and the
deploy action kinds stay advisory (no write connector is registered). True, with
``NS_DEPLOY_APPLY_REGISTER_CONTAINER`` naming the Cosmos container that holds the ownership
register: the approval store and a Cosmos register store are built and attached with
``configure_apply``, and, at application startup (after the action plane is composed), the
``DeployConnector`` is registered into the action plane's write targets so a drafted deploy
intent resolves a connector. Enabled but incomplete (no register container, no Cosmos account
outside local, no customer binding) is logged by reason and leaves everything unconfigured.

The approval store is per process and in memory, so the executor worker (a separate process)
cannot read it: the worker skips the deploy connector (``deploy_sources_unconfigured``) until a
durable ``PlanApprovals`` exists. That is fail closed: an intent approved here does not execute
elsewhere. No Fabric/ARM provisioner is wired, so an apply that needs one stays
``capability_unavailable``; uninstall is dry-run only. No secret is read.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.deploy.register import RegisterStore
from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore
from neurosphere_workers.runtime.factories import (
    DeploySources,
    DeployWriteSettings,
    register_deploy_target,
)
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_api.deploy.apply.approvals import DEFAULT_APPROVAL_TTL_SECONDS, PlanApprovalStore
from neurosphere_api.deploy.apply.router import configure_apply
from neurosphere_api.ingest.bootstrap import (
    _close_on_shutdown,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_api.runtime.settings import AuthSettings, StoreSettings

__all__ = ["DeployApplySettings", "configure_apply_from_settings"]

_log = logging.getLogger("neurosphere_api.deploy.apply")
_COSMOS_ACCOUNT_ENV: Final = "NS_COSMOS_ACCOUNT"


class DeployApplySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_DEPLOY_APPLY_", frozen=True, extra="forbid")

    # Opt-in: false leaves the apply routes failing closed with 503 (apply_not_configured).
    enabled: bool = False
    # The Cosmos container of the ownership register (partition key /deployment_id).
    register_container: str | None = Field(default=None, min_length=1, max_length=255)
    approval_ttl_seconds: float = Field(default=DEFAULT_APPROVAL_TTL_SECONDS, gt=0, le=604800)


def _customer(settings: Settings) -> str | None:
    try:
        return AuthSettings().resolved_customer_id(settings.env)
    except ValidationError:
        return None


def _register_on_startup(
    app: FastAPI, settings: Settings, approvals: PlanApprovalStore, register: RegisterStore
) -> None:
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[Any]:
        async with original(application) as state:
            targets = getattr(application.state, "write_targets", None)
            if isinstance(targets, WriteTargetRegistry):
                registered = register_deploy_target(
                    targets,
                    settings=settings,
                    customer_id=_customer(settings),
                    deploy=DeployWriteSettings(enabled=True),
                    sources=DeploySources(approvals=approvals, register=register),
                )
                _log.info("deploy write target registered: %s", registered)
            else:
                # Action plane not composed: deploy intents stay advisory (fail closed).
                _log.error("deploy write target not registered: action plane unavailable")
            yield state

    app.router.lifespan_context = lifespan


def configure_apply_from_settings(
    app: FastAPI,
    settings: Settings,
    apply_settings: DeployApplySettings | None = None,
    *,
    register: RegisterStore | None = None,
) -> bool:
    """Wire apply/preview when ``NS_DEPLOY_APPLY_ENABLED`` is set. True when configured.

    ``register`` is a test seam; production builds a ``CosmosRegisterStore`` from
    ``NS_DEPLOY_APPLY_REGISTER_CONTAINER`` and the ``NS_STORE_*`` database.
    """
    conf = apply_settings or DeployApplySettings()
    if not conf.enabled:
        return False
    if _customer(settings) is None:
        _log.error("deploy apply not configured: no customer binding")
        return False
    lifetime: ClientLifetime | None = None
    if register is None:
        if conf.register_container is None:
            _log.error("deploy apply not configured: NS_DEPLOY_APPLY_REGISTER_CONTAINER is unset")
            return False
        try:
            database = StoreSettings().database
            lifetime = ClientLifetime()
            client = create_cosmos_client(
                settings, lifetime=lifetime, account=os.environ.get(_COSMOS_ACCOUNT_ENV)
            )
        except Exception as exc:  # reason by type only; never a value
            _log.error(
                "deploy apply not configured: register store failed (%s)", type(exc).__name__
            )
            return False
        register = CosmosRegisterStore.from_client(
            client, database=database, container=conf.register_container
        )
    approvals = PlanApprovalStore(ttl_seconds=conf.approval_ttl_seconds)
    configure_apply(app, approvals=approvals, register=register)
    _register_on_startup(app, settings, approvals, register)
    if lifetime is not None:
        app.state.deploy_apply_lifetime = lifetime
        _close_on_shutdown(app, lifetime)
    return True
