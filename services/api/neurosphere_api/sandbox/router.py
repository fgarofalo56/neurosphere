"""Sandbox API (PRP-24 item 2): ``/api/v1/sandbox``.

Isolation is enforced here on the server (clarification 8): the repository behind these routes is
built with a fixed database/container allowlist (``sandbox-neurosphere``; ``sandbox-entities``,
``sandbox-relations``) and the router never accepts a container, database or "sandbox" flag from
the caller. No real-data container is reachable through this module, and nothing here reads a
sandbox header, so a client sending one to any other route gets nothing special.

Authorization: reads need ``data.read``, the reset write needs ``config.manage`` (D4, no new
permission). Sandbox data is ONE shared synthetic dataset (customer ``synthco``), not tenant data,
so the routes require the permission but do not filter by the caller's domains.

No credentials, no egress: the Cosmos store is built only when ``NS_ENV=local`` (emulator key from
the environment, via ``neurosphere_core.clients``); any other environment answers 503 until a
repository is installed on ``app.state.sandbox_repository``.

This module deliberately has no ``from __future__ import annotations``: FastAPI must see real
annotation objects on the route functions.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from neurosphere_core.auth.scope import Permission
from neurosphere_core.clients.factories import create_cosmos_client
from neurosphere_core.clients.lifetime import ClientLifetime
from neurosphere_core.cloud import Settings, load_settings
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.routers import RouterRegistry
from neurosphere_api.sandbox.models import EntityPage, ResetResult, SandboxKind, SandboxSummary
from neurosphere_api.sandbox.repository import (
    MAX_PAGE_SIZE,
    RELATIONS_CONTAINER,
    CosmosSandboxStore,
    SandboxRepository,
)

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/sandbox"
DEFAULT_PAGE_SIZE: Final = 25

_ATTR: Final = "sandbox_repository"
_LIFETIME_ATTR: Final = "sandbox_lifetime"


def get_repository(request: Request) -> SandboxRepository:
    """The app's sandbox repository; built lazily against the local emulator, else 503."""
    state = request.app.state
    existing = getattr(state, _ATTR, None)
    if isinstance(existing, SandboxRepository):
        return existing
    settings: Settings = load_settings()
    if settings.env != "local":
        raise DependencyTransientError(
            "sandbox store is not configured", reason="sandbox_store_unavailable"
        )
    lifetime = ClientLifetime()
    client = create_cosmos_client(settings, lifetime=lifetime)
    repo = SandboxRepository(CosmosSandboxStore(client))
    setattr(state, _LIFETIME_ATTR, lifetime)
    setattr(state, _ATTR, repo)
    return repo


Repo = Annotated[SandboxRepository, Depends(get_repository)]
ReadScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
ManageScope = Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))]


def build_router() -> APIRouter:
    router = APIRouter(tags=["sandbox"])

    @router.get("/status", response_model=SandboxSummary)
    async def status(_scope: ReadScope, repo: Repo) -> SandboxSummary:
        counts = dict(await repo.counts_by_kind())
        relations = await repo.count_container(RELATIONS_CONTAINER)
        return SandboxSummary(
            database=repo.database,
            counts=counts,
            relations=relations,
            total=sum(counts.values()) + relations,
        )

    @router.get("/entities", response_model=EntityPage)
    async def entities(
        _scope: ReadScope,
        repo: Repo,
        kind: Annotated[SandboxKind, Query()],
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> EntityPage:
        # Fetch one extra row to learn whether another page exists.
        rows = await repo.list_entities(kind, limit + 1, offset)
        more = len(rows) > limit
        return EntityPage(
            kind=kind,
            items=rows[:limit],
            limit=limit,
            offset=offset,
            next_offset=offset + limit if more else None,
        )

    @router.post("/reset", response_model=ResetResult)
    async def reset(_scope: ManageScope, repo: Repo) -> ResetResult:
        return ResetResult(deleted=await repo.reset())

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
