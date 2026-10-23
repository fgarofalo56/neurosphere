"""Shared builders for the admission tests (synthetic data only)."""

from __future__ import annotations

import hashlib

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.scope import IdentityScope


class FakeClock:
    """Deterministic monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def domain_id(name: str, cloud: str = "commercial", customer: str = "contoso") -> str:
    return f"{cloud}:{customer}:catalog:domain:{name}"


def make_scope(
    domains: tuple[str, ...],
    *,
    cloud: str = "commercial",
    customer: str = "contoso",
    principal: str = "a",
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": f"{cloud}:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": f"p-{principal}",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [domain_id(d, cloud, customer) for d in domains],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(f"{principal}:{domains}".encode()).hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
