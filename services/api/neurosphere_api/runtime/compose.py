"""``compose_app``: the settings-driven production composition root (PRP-29 item 1, C5).

``create_app`` stays a bare application (``openapi_export`` and the route tests use it);
``neurosphere_api.main.create`` calls :func:`compose_app` on it. Composition:

1. installs the CORS allow-list when ``NS_CORS_ALLOWED_ORIGINS`` is set (a wildcard raises);
2. runs every builder in order (``runtime/builders``), recording one status per component;
3. sets ``app.state.health_probes`` to the environment probes plus ``composition`` and
   ``app.state.composition`` to the status registry;
4. wraps the lifespan: at startup, when a Cosmos client was built from settings, ``NS_ENV=local``
   runs ``ensure_local_containers`` on the emulator and every other env only checks that the
   declared containers exist (step ``cosmos_containers``; it never creates anything); then the
   builders' startup hooks run. At shutdown the hooks run and the composition's clients close.

It adds no route, so the exported OpenAPI document is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, Final

from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import FastAPI
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.stores import CONTAINERS, ensure_local_containers

from neurosphere_api.health.probes import DependencyProbe, classify, probes_from_env
from neurosphere_api.runtime.builders import (
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
    CompositionState,
    default_builders,
)
from neurosphere_api.runtime.cors import install_cors
from neurosphere_api.runtime.overrides import CompositionOverrides
from neurosphere_api.runtime.readiness import install_readiness
from neurosphere_api.runtime.status import ComponentRegistry

__all__ = [
    "CONTAINER_STEP",
    "CONTAINER_STEP_TIMEOUT_SECONDS",
    "STATE_ATTRIBUTE",
    "compose_app",
]

STATE_ATTRIBUTE: Final = "composition"
CONTAINER_STEP: Final = "cosmos_containers"
CONTAINER_STEP_TIMEOUT_SECONDS: Final = 60.0

_log = logging.getLogger("neurosphere_api.runtime")


class _MissingContainerError(Exception):
    pass


def _cosmos_from_settings(state: CompositionState) -> Any:
    account = state.store_settings().cosmos_account
    return create_cosmos_client(state.settings, lifetime=state.lifetime, account=account)


def _claim(state: CompositionState, builders: Sequence[BuilderSpec]) -> None:
    for spec in builders:
        for name in spec.components:
            if not state.registry.is_known(name):
                raise ValueError(f"builder {spec.name} claims unknown component {name}")
            if name in state.owners:
                owner = state.owners[name]
                raise ValueError(f"component {name} claimed by {owner} and {spec.name}")
            state.owners[name] = spec.name


def _run_builders(state: CompositionState, builders: Sequence[BuilderSpec]) -> None:
    _claim(state, builders)
    registry = state.registry
    for spec in builders:
        try:
            spec.build(BuildContext(state, spec))
        except Exception as exc:
            _log.error("builder %s raised %s", spec.name, type(exc).__name__)
            for name in spec.components:
                if not registry.reported(name):
                    registry.failed(name, "build_error")
        for name in spec.components:
            if not registry.reported(name):
                registry.not_built(name)


async def _verify_containers(client: Any, database: str) -> None:
    """Outside local: never create; every declared container must already exist (IaC)."""
    db = client.get_database_client(database)
    for spec in CONTAINERS:
        try:
            await db.get_container_client(spec.name).read()
        except CosmosResourceNotFoundError:
            raise _MissingContainerError from None


async def _container_step(state: CompositionState) -> None:
    client = state.cosmos
    if client is None or state.cosmos_overridden:
        return  # no settings-built client: nothing to provision or verify
    registry = state.registry
    try:
        database = state.store_settings().database
        async with asyncio.timeout(CONTAINER_STEP_TIMEOUT_SECONDS):
            if state.settings.env == "local":
                await ensure_local_containers(client, state.settings, database=database)
            else:
                await _verify_containers(client, database)
    except ComponentUnavailableError as exc:
        registry.failed(CONTAINER_STEP, exc.reason)
    except _MissingContainerError:
        registry.failed(CONTAINER_STEP, "container_missing")
    except Exception as exc:
        registry.failed(CONTAINER_STEP, classify(exc))
        _log.warning("cosmos container step failed: %s", type(exc).__name__)


async def _run_startup(state: CompositionState) -> None:
    await _container_step(state)
    registry = state.registry
    for builder_name, hook in state.startup:
        try:
            await hook()
        except Exception as exc:
            _log.error("startup hook of %s raised %s", builder_name, type(exc).__name__)
            for component, owner in sorted(state.owners.items()):
                if owner == builder_name and registry.get(component).state == "ok":
                    registry.failed(component, "startup_failed")


def _wrap_lifespan(app: FastAPI, state: CompositionState) -> None:
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[Any]:
        try:
            await _run_startup(state)
            async with original(application) as inner:
                yield inner
        finally:
            for hook in reversed(state.shutdown):
                try:
                    await hook()
                except Exception as exc:
                    _log.warning("shutdown hook raised %s", type(exc).__name__)
            await state.lifetime.aclose()

    app.router.lifespan_context = lifespan


def compose_app(
    app: FastAPI,
    settings: Settings,
    overrides: CompositionOverrides | None = None,
    *,
    builders: Sequence[BuilderSpec] | None = None,
    environ: Mapping[str, str] | None = None,
    env_probes: Sequence[DependencyProbe] | None = None,
) -> ComponentRegistry:
    """Compose ``app`` from settings and return the component status registry.

    ``overrides``, ``builders`` and ``env_probes`` are for tests only (``main.create`` passes
    none of them). ``environ`` feeds the environment readiness probes (default ``os.environ``);
    the settings classes read the process environment themselves.
    """
    env = dict(os.environ if environ is None else environ)
    install_cors(app)
    registry = ComponentRegistry()
    state = CompositionState(
        app=app,
        settings=settings,
        overrides=overrides or CompositionOverrides(),
        registry=registry,
        environ=env,
        lifetime=ClientLifetime(),
    )
    state.cosmos_factory = lambda: _cosmos_from_settings(state)
    _run_builders(state, tuple(default_builders() if builders is None else builders))
    setattr(app.state, STATE_ATTRIBUTE, registry)
    probes = probes_from_env(env) if env_probes is None else tuple(env_probes)
    install_readiness(app, registry, probes)
    _wrap_lifespan(app, state)
    for status in registry.blocking():
        _log.info("composition: %s is %s", status.name, status.code)
    return registry
