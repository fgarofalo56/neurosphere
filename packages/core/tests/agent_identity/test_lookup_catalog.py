"""CatalogAliasLookup and declare_agent_alias against the in-memory catalog repository."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    CatalogAliasLookup,
    agent_alias_key,
    declare_agent_alias,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors.taxonomy import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .helpers import FakeClock, agent, agent_id, dom, make_scope

NS = "acme"


async def _setup() -> tuple[InMemoryCatalogRepository, IdentityScope]:
    repo = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    for name in ("one", "two"):
        await repo.create_entity(scope, agent(NS, name, "a"))
    return repo, scope


def _tick() -> Callable[[], datetime]:
    state = {"t": datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC)}

    def clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return clock


async def test_create_then_idempotent_then_repoint() -> None:
    repo, scope = await _setup()
    clock = _tick()
    key = agent_alias_key("foundry", "asst-1")
    kw = {"source_id": "foundry", "external_agent_id": "asst-1", "clock": clock}

    first = await declare_agent_alias(repo, scope, target_agent_id=agent_id(NS, "one"), **kw)
    assert first.outcome == "created" and first.alias_id and first.retired_alias_id is None
    assert await repo.resolve_alias(scope, key) == agent_id(NS, "one")

    again = await declare_agent_alias(repo, scope, target_agent_id=agent_id(NS, "one"), **kw)
    assert again.outcome == "unchanged" and again.alias_id is None

    moved = await declare_agent_alias(repo, scope, target_agent_id=agent_id(NS, "two"), **kw)
    assert moved.outcome == "repointed"
    assert moved.retired_alias_id == first.alias_id
    assert moved.alias_id not in (None, first.alias_id)
    assert await repo.resolve_alias(scope, key) == agent_id(NS, "two")

    back = await declare_agent_alias(repo, scope, target_agent_id=agent_id(NS, "one"), **kw)
    assert back.outcome == "repointed" and back.retired_alias_id == moved.alias_id
    assert await repo.resolve_alias(scope, key) == agent_id(NS, "one")


async def test_declare_rejects_foreign_or_non_agent_target() -> None:
    repo, scope = await _setup()
    for target in (
        "commercial:other:foundry:agent:one",
        "government:acme:foundry:agent:one",
        f"commercial:{NS}:foundry:tool:one",
    ):
        with pytest.raises(InvalidSchemaError):
            await declare_agent_alias(
                repo,
                scope,
                source_id="foundry",
                external_agent_id="x",
                target_agent_id=target,
            )


async def test_catalog_lookup_and_resolver_end_to_end() -> None:
    repo, scope = await _setup()
    lookup = CatalogAliasLookup(repo, lambda: scope)
    assert await lookup.lookup(agent_alias_key("foundry", "asst-1")) is None
    await declare_agent_alias(
        repo,
        scope,
        source_id="foundry",
        external_agent_id="asst-1",
        target_agent_id=agent_id(NS, "one"),
    )
    assert await lookup.lookup(agent_alias_key("foundry", "asst-1")) == agent_id(NS, "one")

    resolver = AgentIdentityResolver(lookup, clock=FakeClock())
    hit = await resolver.resolve("commercial", NS, "foundry", "asst-1", None)
    assert (hit.status, hit.canonical_id) == ("alias", agent_id(NS, "one"))
    miss = await resolver.resolve("commercial", NS, "foundry", "asst-2", None)
    assert miss.status == "derived"


async def test_lookup_in_another_customer_scope_sees_nothing() -> None:
    repo, scope = await _setup()
    await declare_agent_alias(
        repo,
        scope,
        source_id="foundry",
        external_agent_id="asst-1",
        target_agent_id=agent_id(NS, "one"),
    )
    other = make_scope("beta", [dom("beta", "a")])
    lookup = CatalogAliasLookup(repo, lambda: other)
    assert await lookup.lookup(agent_alias_key("foundry", "asst-1")) is None
