"""Shared builders for fixture-search tests (offline, no network)."""

from __future__ import annotations

import hashlib
from typing import Any

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope

CUSTOMER = "acme"


def cid(etype: str, local: str, customer: str = CUSTOMER, cloud: str = "commercial") -> str:
    return f"{cloud}:{customer}:cat:{etype}:{local}"


def make_scope(
    domains: list[str],
    *,
    cloud: str = "commercial",
    customer: str = CUSTOMER,
    grants: list[str] | None = None,
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer,
        "principal": {
            "principal_id": f"{cloud}:{customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [],
        "allowed_domains": domains,
        "allowed_resources": [{"resource_id": g, "permissions": ["read"]} for g in grants or []],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
    }
    return IdentityScope.model_validate(payload)


def corpus() -> list[dict[str, Any]]:
    """Two domains (each a domain doc plus 12 agents); all agents mention 'triage'."""
    docs: list[dict[str, Any]] = []
    for dom in ("alpha", "beta"):
        did = cid("domain", dom)
        docs.append({"id": did, "name": f"{dom} domain"})
        for i in range(12):
            docs.append(
                {
                    "id": cid("agent", f"{dom}-{i:02d}"),
                    "domain_id": did,
                    "name": f"triage agent {i}",
                    "description": "routes support tickets triage " * (1 + i % 3),
                }
            )
    return docs
