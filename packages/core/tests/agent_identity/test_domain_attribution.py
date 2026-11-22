"""Domain attribution (PRP-137 item 6b): the resolver supplies a domain for events with none."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.agent_identity import (
    AgentIdentityResolver,
    AgentIdentitySettings,
    CatalogAgentDomainLookup,
    derive_agent_id,
    is_owned_domain,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository

from .helpers import FakeClock, StubLookup, agent, agent_id, dom, make_scope

NS = "acme"
OWN = agent_id(NS, "real")
DOM_AGENT = dom(NS, "agent-dom")
DOM_SETTING = dom(NS, "discovery")


class StubDomains:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def domain_of(self, agent_id: str) -> str | None:
        self.calls.append(agent_id)
        if self.error is not None:
            raise self.error
        return self.values.get(agent_id)


def _resolver(
    lookup: StubLookup,
    domains: StubDomains | None = None,
    *,
    discovery: str | None = None,
    clock: FakeClock | None = None,
    **kw: Any,
) -> tuple[AgentIdentityResolver, FakeClock]:
    clock = clock or FakeClock()
    resolver = AgentIdentityResolver(
        lookup, clock=clock, domain_lookup=domains, discovery_domain_id=discovery, **kw
    )
    return resolver, clock


async def _resolve(
    r: AgentIdentityResolver,
    external: str | None,
    canonical: str | None = None,
    domain: str | None = None,
):
    return await r.resolve("commercial", NS, "foundry", external, canonical, domain)


async def test_event_domain_is_kept_and_nothing_is_looked_up() -> None:
    domains = StubDomains({OWN: DOM_AGENT})
    r, _ = _resolver(StubLookup({"ext": OWN}), domains, discovery=DOM_SETTING)
    res = await _resolve(r, "ext", None, dom(NS, "mine"))
    assert (res.domain_id, res.domain_source) == (dom(NS, "mine"), "event")
    assert domains.calls == []
    assert r.stats.domain_unattributed == r.stats.domain_from_agent == 0


async def test_alias_takes_the_agents_catalog_domain() -> None:
    r, _ = _resolver(StubLookup({"ext": OWN}), StubDomains({OWN: DOM_AGENT}), discovery=DOM_SETTING)
    res = await _resolve(r, "ext")
    assert (res.status, res.domain_id, res.domain_source) == ("alias", DOM_AGENT, "agent")
    assert r.stats.domain_from_agent == 1


async def test_declared_takes_the_agents_catalog_domain() -> None:
    r, _ = _resolver(StubLookup(), StubDomains({OWN: DOM_AGENT}))
    res = await _resolve(r, None, OWN)
    assert (res.status, res.domain_id, res.domain_source) == ("declared", DOM_AGENT, "agent")


async def test_derived_takes_the_discovery_setting() -> None:
    r, _ = _resolver(StubLookup(), StubDomains(), discovery=DOM_SETTING)
    res = await _resolve(r, "ext")
    assert (res.status, res.domain_id, res.domain_source) == ("derived", DOM_SETTING, "setting")
    assert res.canonical_id == derive_agent_id("commercial", NS, "foundry", "ext")
    assert r.stats.domain_from_setting == 1


@pytest.mark.parametrize(
    "setting",
    [
        None,
        "",
        "commercial:other:neurosphere:domain:d",  # another customer
        "government:acme:neurosphere:domain:d",  # another cloud
        "commercial:acme:neurosphere:agent:d",  # not a domain
        "not a canonical id",
    ],
)
async def test_derived_without_a_usable_setting_is_unattributed(setting: str | None) -> None:
    r, _ = _resolver(StubLookup(), StubDomains(), discovery=setting)
    res = await _resolve(r, "ext")
    assert (res.domain_id, res.domain_source) == (None, "none")
    assert r.stats.domain_unattributed == 1
    assert r.stats.domain_from_setting == 0


async def test_none_status_is_unattributed_even_with_a_setting() -> None:
    r, _ = _resolver(StubLookup(), StubDomains(), discovery=DOM_SETTING)
    res = await _resolve(r, None)
    assert (res.status, res.domain_id, res.domain_source) == ("none", None, "none")


async def test_alias_target_without_a_visible_domain_is_unattributed_not_setting() -> None:
    r, _ = _resolver(StubLookup({"ext": OWN}), StubDomains(), discovery=DOM_SETTING)
    res = await _resolve(r, "ext")
    assert (res.status, res.domain_id, res.domain_source) == ("alias", None, "none")
    assert r.stats.domain_unattributed == 1


async def test_agent_domain_of_another_customer_is_ignored() -> None:
    foreign = "commercial:other:neurosphere:domain:d"
    r, _ = _resolver(StubLookup({"ext": OWN}), StubDomains({OWN: foreign}))
    res = await _resolve(r, "ext")
    assert res.domain_id is None


async def test_domain_lookup_is_cached_with_positive_and_negative_ttl() -> None:
    domains = StubDomains({OWN: DOM_AGENT})
    r, clock = _resolver(
        StubLookup({"ext": OWN, "ext2": agent_id(NS, "other")}),
        domains,
        positive_ttl_seconds=60,
        negative_ttl_seconds=10,
    )
    await _resolve(r, "ext")
    await _resolve(r, "ext")
    assert domains.calls == [OWN]  # cached
    await _resolve(r, "ext2")
    await _resolve(r, "ext2")
    assert domains.calls == [OWN, agent_id(NS, "other")]  # negative cached too
    clock.now += 11
    await _resolve(r, "ext2")
    assert len(domains.calls) == 3  # negative expired
    await _resolve(r, "ext")
    assert len(domains.calls) == 3  # positive still valid
    clock.now += 60
    await _resolve(r, "ext")
    assert len(domains.calls) == 4


async def test_domain_cache_is_bounded() -> None:
    values = {agent_id(NS, f"a{i}"): DOM_AGENT for i in range(5)}
    domains = StubDomains(values)
    lookup = StubLookup({f"e{i}": agent_id(NS, f"a{i}") for i in range(5)})
    r, _ = _resolver(lookup, domains, max_entries=2)
    for i in range(5):
        await _resolve(r, f"e{i}")
    assert len(r._domain_cache) <= 2


async def test_domain_lookup_failure_propagates_and_is_counted() -> None:
    domains = StubDomains({OWN: DOM_AGENT})
    domains.error = RuntimeError("catalog down")
    r, _ = _resolver(StubLookup({"ext": OWN}), domains, discovery=DOM_SETTING)
    with pytest.raises(RuntimeError):
        await _resolve(r, "ext")
    assert r.stats.lookup_failures == 1
    domains.error = None  # recovered: nothing was cached from the failure
    assert (await _resolve(r, "ext")).domain_id == DOM_AGENT


async def test_catalog_domain_lookup_reads_the_scoped_entity() -> None:
    repo = InMemoryCatalogRepository()
    scope = make_scope(NS, [dom(NS, "a")])
    await repo.create_entity(scope, agent(NS, "one", "a"))
    lookup = CatalogAgentDomainLookup(repo, lambda: scope)
    assert await lookup.domain_of(agent_id(NS, "one")) == dom(NS, "a")
    assert await lookup.domain_of(agent_id(NS, "missing")) is None
    narrow = make_scope(NS, [dom(NS, "elsewhere")])  # entity not visible in this scope
    assert (
        await CatalogAgentDomainLookup(repo, lambda: narrow).domain_of(agent_id(NS, "one")) is None
    )


def test_is_owned_domain() -> None:
    assert is_owned_domain(DOM_SETTING, "commercial", NS)
    assert not is_owned_domain(DOM_SETTING, "commercial", "other")
    assert not is_owned_domain(DOM_SETTING, "government", NS)
    assert not is_owned_domain(agent_id(NS, "x"), "commercial", NS)
    assert not is_owned_domain(None, "commercial", NS)


def test_discovery_domain_setting_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AgentIdentitySettings().discovery_domain is None
    monkeypatch.setenv("NS_AGENT_IDENTITY_DISCOVERY_DOMAIN", DOM_SETTING)
    assert AgentIdentitySettings().discovery_domain == DOM_SETTING
