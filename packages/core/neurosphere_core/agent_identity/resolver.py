"""Resolve a telemetry agent to a canonical agent id (alias first, derived otherwise).

Order, first match wins:

1. ``canonical_agent_id`` present and an owned agent (same cloud and customer, type ``agent``):
   ``declared``, unchanged.
2. No external id (and no usable canonical id): ``none``; the id stays ``None``.
3. The external id has an active alias to an owned agent: ``alias``.
4. No alias: ``derived`` (``derive_agent_id``).
5. An alias to another cloud or customer or to a non-agent: ``derived``, counted as
   ``alias_target_invalid``. A resolution never crosses cloud or customer.

A present-but-not-owned ``canonical_agent_id`` is treated as absent: the external id decides,
the result carries reason ``canonical_not_owned`` and ``alias_target_invalid`` is incremented.
With no external id either, the result is ``none``.

A lookup exception propagates (and is counted); it never falls back to a derived id, because
that would silently file telemetry under the wrong agent while the catalog is unavailable.

Domain attribution (item 6b): OTLP events carry no domain, yet catalog edges and draft agents
need one. ``resolve`` therefore also returns a domain for an event that has none:

* the event's own domain is kept unchanged (``domain_source == "event"``);
* ``alias``/``declared``: the resolved agent's catalog domain (``agent``);
* ``derived``: the operator discovery domain when it is an owned domain id (``setting``);
* otherwise ``None`` (``none``, counted ``domain_unattributed``).

A domain lookup exception propagates like the alias lookup.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import Any, Final, Literal

from neurosphere_core.agent_identity.keys import (
    agent_alias_key,
    derive_agent_id,
    is_owned_agent,
    is_owned_domain,
)
from neurosphere_core.agent_identity.lookup import AgentDomainLookup, AliasLookup

ResolutionStatus = Literal["alias", "derived", "declared", "none"]
DomainSource = Literal["event", "agent", "setting", "none"]

REASON_CANONICAL_NOT_OWNED: Final = "canonical_not_owned"
REASON_ALIAS_TARGET_INVALID: Final = "alias_target_invalid"

_CacheKey = tuple[str, str, str, str, str]
_DomainKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class AgentResolution:
    canonical_id: str | None
    status: ResolutionStatus
    reason: str | None = None
    domain_id: str | None = None
    domain_source: DomainSource = "none"


@dataclass(slots=True)
class ResolutionStats:
    """Counters only; no ids or content, so they are safe as status or metric labels."""

    resolved_alias: int = 0
    derived: int = 0
    declared: int = 0
    no_agent_id: int = 0
    alias_target_invalid: int = 0
    lookup_failures: int = 0
    drafts_created: int = 0
    contributions_moved: int = 0
    domain_from_agent: int = 0
    domain_from_setting: int = 0
    domain_unattributed: int = 0

    def snapshot(self) -> dict[str, int]:
        return {f.name: int(getattr(self, f.name)) for f in fields(self)}


class AgentIdentityResolver:
    def __init__(
        self,
        lookup: AliasLookup,
        *,
        clock: Callable[[], float],
        positive_ttl_seconds: float = 60,
        negative_ttl_seconds: float = 15,
        max_entries: int = 10_000,
        domain_lookup: AgentDomainLookup | None = None,
        discovery_domain_id: str | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._lookup = lookup
        self._domain_lookup = domain_lookup
        self._discovery = discovery_domain_id or None
        self._clock = clock
        self._positive = positive_ttl_seconds
        self._negative = negative_ttl_seconds
        self._max = max_entries
        self._cache: OrderedDict[_CacheKey, tuple[str | None, float]] = OrderedDict()
        self._domain_cache: OrderedDict[_DomainKey, tuple[str | None, float]] = OrderedDict()
        self.stats = ResolutionStats()

    async def resolve(
        self,
        cloud: str,
        customer: str,
        source_id: str,
        external_agent_id: str | None,
        canonical_agent_id: str | None,
        domain_id: str | None = None,
    ) -> AgentResolution:
        """Resolve the agent, and a domain when the event has none (``domain_id`` is its own)."""
        found = await self._resolve_agent(
            cloud, customer, source_id, external_agent_id, canonical_agent_id
        )
        if domain_id:
            return replace(found, domain_id=domain_id, domain_source="event")
        domain, origin = await self._attribute(cloud, customer, found)
        return replace(found, domain_id=domain, domain_source=origin)

    async def _attribute(
        self, cloud: str, customer: str, found: AgentResolution
    ) -> tuple[str | None, DomainSource]:
        if found.status in ("alias", "declared") and found.canonical_id is not None:
            domain = await self._cached_domain(cloud, customer, found.canonical_id)
            if domain is not None and is_owned_domain(domain, cloud, customer):
                self.stats.domain_from_agent += 1
                return domain, "agent"
        elif found.status == "derived" and is_owned_domain(self._discovery, cloud, customer):
            self.stats.domain_from_setting += 1
            return self._discovery, "setting"
        self.stats.domain_unattributed += 1
        return None, "none"

    async def _resolve_agent(
        self,
        cloud: str,
        customer: str,
        source_id: str,
        external_agent_id: str | None,
        canonical_agent_id: str | None,
    ) -> AgentResolution:
        reason: str | None = None
        if canonical_agent_id is not None:
            if is_owned_agent(canonical_agent_id, cloud, customer):
                self.stats.declared += 1
                return AgentResolution(canonical_agent_id, "declared")
            self.stats.alias_target_invalid += 1
            reason = REASON_CANONICAL_NOT_OWNED
        if not external_agent_id:
            self.stats.no_agent_id += 1
            return AgentResolution(None, "none", reason)
        target = await self._cached_lookup(cloud, customer, source_id, external_agent_id)
        if target is not None:
            if is_owned_agent(target, cloud, customer):
                self.stats.resolved_alias += 1
                return AgentResolution(target, "alias", reason)
            self.stats.alias_target_invalid += 1
            reason = reason or REASON_ALIAS_TARGET_INVALID
        self.stats.derived += 1
        derived = derive_agent_id(cloud, customer, source_id, external_agent_id)
        return AgentResolution(derived, "derived", reason)

    async def _cached_lookup(
        self, cloud: str, customer: str, source_id: str, external_agent_id: str
    ) -> str | None:
        key = agent_alias_key(source_id, external_agent_id)
        ck: _CacheKey = (cloud, customer, key.alias_source_id, key.alias_kind, key.alias_value)
        now = self._clock()
        hit = self._cache.get(ck)
        if hit is not None:
            if now < hit[1]:
                return hit[0]
            del self._cache[ck]
        try:
            found = await self._lookup.lookup(key)
        except Exception:
            self.stats.lookup_failures += 1
            raise
        ttl = self._positive if found is not None else self._negative
        self._store(self._cache, ck, found, now + ttl, now)
        return found

    async def _cached_domain(self, cloud: str, customer: str, agent_id: str) -> str | None:
        if self._domain_lookup is None:
            return None
        dk: _DomainKey = (cloud, customer, agent_id)
        now = self._clock()
        hit = self._domain_cache.get(dk)
        if hit is not None:
            if now < hit[1]:
                return hit[0]
            del self._domain_cache[dk]
        try:
            found = await self._domain_lookup.domain_of(agent_id)
        except Exception:
            self.stats.lookup_failures += 1
            raise
        ttl = self._positive if found is not None else self._negative
        self._store(self._domain_cache, dk, found, now + ttl, now)
        return found

    def _store(
        self,
        cache: OrderedDict[Any, tuple[str | None, float]],
        ck: Any,
        value: str | None,
        expires: float,
        now: float,
    ) -> None:
        if len(cache) >= self._max:
            for old in [k for k, (_v, exp) in cache.items() if exp <= now]:
                del cache[old]
            while len(cache) >= self._max:
                cache.popitem(last=False)
        cache[ck] = (value, expires)
