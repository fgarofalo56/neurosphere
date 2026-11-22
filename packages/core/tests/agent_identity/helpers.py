"""Builders for the agent identity tests (scope, agents, fake clock, stub lookup)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog.protocol import AliasKey
from neurosphere_core.scope import IdentityScope

_VALID = Path(__file__).resolve().parents[3] / "contracts/schemas/catalog/v1/examples/valid"


def dom(ns: str, name: str) -> str:
    return f"commercial:{ns}:neurosphere:domain:{name}"


def agent_id(ns: str, name: str) -> str:
    return f"commercial:{ns}:foundry:agent:{name}"


def make_scope(ns: str, domains: list[str]) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": ns,
        "principal": {
            "principal_id": f"commercial:{ns}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


def agent(ns: str, name: str, domain: str) -> Agent:
    raw = json.loads((_VALID / "agent.minimal-and-typical.json").read_text(encoding="utf-8"))
    raw.update(
        id=agent_id(ns, name),
        customer_id=ns,
        domain_id=dom(ns, domain),
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    return Agent.model_validate(raw)


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class StubLookup:
    """Returns canned values by alias value; counts calls; can raise."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.calls: list[AliasKey] = []
        self.error: Exception | None = None

    async def lookup(self, key: AliasKey) -> str | None:
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        return self.values.get(key.alias_value)
