"""Alias lookup over the catalog, and the retire-then-add alias declaration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from neurosphere_contracts.catalog.v1.alias import Alias

from neurosphere_core.agent_identity.keys import agent_alias_key, is_owned_agent, slug
from neurosphere_core.catalog.protocol import AliasKey, CatalogRepository
from neurosphere_core.errors.taxonomy import InvalidSchemaError
from neurosphere_core.scope import IdentityScope


@runtime_checkable
class AliasLookup(Protocol):
    async def lookup(self, key: AliasKey) -> str | None:
        """Canonical id the active alias maps to, or None (missing or out of scope)."""
        raise NotImplementedError


class CatalogAliasLookup:
    """``AliasLookup`` over ``CatalogRepository.resolve_alias`` in the caller's scope."""

    def __init__(self, repo: CatalogRepository, scope_getter: Callable[[], IdentityScope]) -> None:
        self._repo = repo
        self._scope_getter = scope_getter

    async def lookup(self, key: AliasKey) -> str | None:
        return await self._repo.resolve_alias(self._scope_getter(), key)


@runtime_checkable
class AgentDomainLookup(Protocol):
    async def domain_of(self, agent_id: str) -> str | None:
        """Catalog domain id of the agent, or None (missing, out of scope, or no domain)."""
        raise NotImplementedError


class CatalogAgentDomainLookup:
    """``AgentDomainLookup`` over ``CatalogRepository.get_entity`` in the caller's scope."""

    def __init__(self, repo: CatalogRepository, scope_getter: Callable[[], IdentityScope]) -> None:
        self._repo = repo
        self._scope_getter = scope_getter

    async def domain_of(self, agent_id: str) -> str | None:
        entity = await self._repo.get_entity(self._scope_getter(), agent_id)
        domain = getattr(entity, "domain_id", None)
        value = getattr(domain, "root", domain)
        return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class DeclaredAlias:
    outcome: Literal["created", "repointed", "unchanged"]
    alias_id: str | None
    retired_alias_id: str | None = None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alias_doc(
    scope: IdentityScope,
    key: AliasKey,
    target: str,
    *,
    suffix: str,
    stamp: str,
    provenance_source: str,
    method: str,
) -> Alias:
    digest = hashlib.sha256(f"{key.alias_value}|{target}|{suffix}".encode()).hexdigest()[:24]
    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": f"{scope.cloud}:{scope.customer_id}:neurosphere:alias:{key.alias_source_id}/{digest}",
        "version": 1,
        "etag": "caller-etag",
        "created_at": stamp,
        "updated_at": stamp,
        "cloud": scope.cloud,
        "customer_id": scope.customer_id,
        "alias_value": key.alias_value,
        "alias_kind": key.alias_kind,
        "alias_source_id": key.alias_source_id,
        "canonical_id": target,
        "entity_type": target.split(":", 4)[3],
        "status": "active",
        "validity": {"valid_from": stamp, "valid_to": None},
        "provenance": {
            "method": method,
            "source_id": provenance_source,
            "recorded_at": stamp,
        },
    }
    return Alias.model_validate(raw)


async def declare_agent_alias(
    repo: CatalogRepository,
    scope: IdentityScope,
    *,
    source_id: str,
    external_agent_id: str,
    target_agent_id: str,
    method: str = "declared",
    clock: Callable[[], datetime] | None = None,
) -> DeclaredAlias:
    """Make ``external_agent_id`` (in ``source_id``) resolve to ``target_agent_id``.

    ``put_alias`` cannot repoint, so a changed target retires the active alias (status change
    on the same document) and adds a new one. Idempotent when the active alias already points
    at the target. The target must be an agent of the scope's cloud and customer; the
    repository additionally rejects targets outside the scope's domains.
    """
    if not is_owned_agent(target_agent_id, scope.cloud, scope.customer_id):
        raise InvalidSchemaError("the alias target must be an agent of the caller's customer")
    key = agent_alias_key(source_id, external_agent_id)
    moment = (clock or (lambda: datetime.now(UTC)))()
    stamp = _stamp(moment)
    current = await repo.resolve_alias(scope, key)
    if current == target_agent_id:
        return DeclaredAlias("unchanged", None)
    retired_id: str | None = None
    if current is not None:
        # put_alias is idempotent for the same mapping and returns the stored active document,
        # which is how the id and etag needed to retire it are recovered.
        probe = _alias_doc(
            scope,
            key,
            current,
            suffix="probe",
            stamp=stamp,
            provenance_source=slug(source_id, "trace"),
            method=method,
        )
        existing = await repo.put_alias(scope, probe)
        body = existing.model_dump(mode="json")
        body["status"] = "retired"
        body["updated_at"] = stamp
        body["validity"]["valid_to"] = stamp
        retired = await repo.put_alias(scope, Alias.model_validate(body))
        retired_id = retired.id
    fresh = _alias_doc(
        scope,
        key,
        target_agent_id,
        suffix=stamp,
        stamp=stamp,
        provenance_source=slug(source_id, "trace"),
        method=method,
    )
    saved = await repo.put_alias(scope, fresh)
    return DeclaredAlias("repointed" if retired_id is not None else "created", saved.id, retired_id)
