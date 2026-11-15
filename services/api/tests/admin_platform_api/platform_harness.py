"""Harness for the platform admin API tests (PRP-44).

Composes the REAL authz builder, a stub data builder (in-memory audit and a shared review policy
registry) and the REAL ``admin_platform`` builder over in-memory stores. Principals:

* ``CUSTOMER_ADMIN``: ``admin`` on FINANCE and the customer-control domain (customer-level
  ``config.manage``).
* ``DOMAIN_ADMIN``: ``admin`` on FINANCE only (config.manage in a domain, not customer-wide).
* ``ANALYST``: analyst in FINANCE (no ``config.manage``).
* ``EXPIRED_ADMIN``: customer-control admin whose role expired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    REVIEW_POLICIES,
    BuildContext,
    BuilderSpec,
)
from neurosphere_api.runtime.builders import admin_platform as builder
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import LoadableReviewPolicyRegistry
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.pricing import InMemoryPriceSnapshotStore
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

__all__ = [
    "ANALYST",
    "BASE",
    "CONTROL",
    "CUSTOMER",
    "CUSTOMER_ADMIN",
    "DOMAIN_ADMIN",
    "EXPIRED_ADMIN",
    "FINANCE",
    "PlatformWorld",
    "budget_body",
    "configure_env",
    "domain_body",
    "policy_body",
    "policy_settings",
    "sheet_body",
    "token_row",
]

CUSTOMER_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ANALYST = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
EXPIRED_ADMIN = "4d5e6f7a-8b9c-4d0e-9f2a-3b4c5d6e7f80"
BASE = "/api/v1/admin/platform"
FINANCE = "commercial:contoso:neurosphere:domain:finance"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def domain_body(domain_id: str = FINANCE, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "domain_id": domain_id,
        "display_name": "Finance",
        "classification": "confidential",
        "residency_region": "eastus2",
        "status": "active",
        "is_control_domain": False,
    }
    body.update(over)
    return body


def budget_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "budget_id": "fin-monthly",
        "domain_id": FINANCE,
        "period": "monthly",
        "amount": "1500.50",
        "currency": "USD",
        "thresholds_percent": [50, 80, 100],
    }
    body.update(over)
    return body


def token_row(model: str, kind: str, price: str, unit: str = "1M") -> dict[str, Any]:
    return {
        "service_name": "Azure OpenAI",
        "sku_name": f"{model} {kind}",
        "unit_of_measure": unit,
        "retail_price": price,
        "token_meter": {"provider": "azure_openai", "model": model, "kind": kind},
    }


def sheet_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": "aoai-2026-11",
        "source": "provider_price_sheet",
        "source_url": "https://example.test/prices",
        "retrieval_date": "2026-11-01",
        "effective_date": "2026-11-01",
        "currency": "USD",
        "clouds": ["commercial"],
        "synthetic": False,
        "notes": "",
        "rows": [
            token_row("gpt-4.1", "input", "2.31"),
            token_row("gpt-4.1", "output", "8.77"),
            token_row("gpt-mini", "input", "0.41"),
        ],
    }
    body.update(over)
    return body


def policy_settings(**over: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "self_approval_forbidden": True,
        "approver_permission": "action.approve",
        "assignment_timeout_seconds": 14400,
        "sla_seconds": 3600,
        "escalation_step_seconds": 7200,
        "max_escalations": 3,
        "expiry_seconds": 259200,
    }
    settings.update(over)
    return settings


def policy_body(maker_checker: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "policy_version": "client-chosen",
        "kind_defaults": [
            {"review_kind": "maker_checker", "policy": maker_checker or policy_settings()},
            {
                "review_kind": "relationship",
                "policy": policy_settings(approver_permission="catalog.curate"),
            },
        ],
        "action_overrides": [],
    }


def _doc(
    object_id: str, memberships: tuple[str, ...], *domains: str, who: Role, expires: float | None
) -> PrincipalPolicy:
    principal = pid(object_id)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=(role(who, *domains, expires_in=expires),),
    )


def seeded_policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    both = (FINANCE, CONTROL)
    repo.put_principal(_doc(CUSTOMER_ADMIN, both, *both, who=Role.ADMIN, expires=None))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), FINANCE, who=Role.ADMIN, expires=None))
    repo.put_principal(_doc(ANALYST, (FINANCE,), FINANCE, who=Role.ANALYST, expires=None))
    repo.put_principal(_doc(EXPIRED_ADMIN, both, *both, who=Role.ADMIN, expires=-10))
    return repo


@dataclass
class PlatformWorld:
    composed: Composed
    repository: InMemoryAdminConfigRepository
    prices: InMemoryPriceSnapshotStore
    policies: LoadableReviewPolicyRegistry
    audit_store: InMemoryAuditStore

    def auth(self, object_id: str) -> dict[str, str]:
        return self.composed.auth(object_id)

    def records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            out.extend(sorted(self.audit_store.raw_documents(chain), key=lambda d: d["sequence"]))
        return out

    @classmethod
    def build(cls, **backends: object) -> PlatformWorld:
        clock = FakeClock()
        repository = InMemoryAdminConfigRepository(cloud="commercial")
        prices = InMemoryPriceSnapshotStore()
        policies = LoadableReviewPolicyRegistry()
        store = InMemoryAuditStore()
        audit = AuditRepository(store)

        def build_data(ctx: BuildContext) -> None:
            ctx.publish(AUDIT_REPOSITORY, audit)
            ctx.publish(REVIEW_POLICIES, policies)
            ctx.ok("audit")

        overrides = CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=seeded_policies(),
            revocation_store=InMemoryRevocationStore(clock=clock),
            clock=clock,
            backends={
                "admin_config_repository": repository,
                "price_snapshot_store": prices,
                **backends,
            },
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock)
        return cls(composed, repository, prices, policies, store)
