"""Harness for the governance policy API tests (PRP-105 item 6). No network, synthetic data.

Composes the REAL authz builder, a stub data builder (in-memory audit, HITL service and catalog
repository) and the REAL ``governance`` builder over the in-memory backend (``NS_ENV=local``,
``NS_GOVPOLICY_BACKEND=memory``), then installs the action plane with NO write connector, so a
``governance_policy_publish`` intent is advisory, exactly as before PRP-108.

Principals (customer ``contoso``):

* ``STEWARD`` / ``STEWARD_2``: domain_steward on FINANCE (manage, propose, curate);
* ``ADMIN``: admin on FINANCE (manage and read, no ``action.propose``);
* ``ANALYST``: analyst on FINANCE (read and propose, no manage);
* ``VIEWER``: viewer on FINANCE (read only);
* ``OPS_STEWARD``: domain_steward on OPERATIONS only;
* ``CONTROL_STEWARD``: domain_steward on the customer control domain only;
* ``AUDITOR``: security_auditor on FINANCE (``govpolicy.read`` without data);
* ``INVESTIGATOR``: interaction_investigator on FINANCE (no governance permission).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    POLICY_VERSION,
    FakeClock,
    make_validator,
    role,
)
from fastapi.testclient import TestClient
from neurosphere_api.actions import configure_action_plane
from neurosphere_api.governance.policy import GovernancePolicyPlane
from neurosphere_api.hitl import RecheckerReviewerAuthorizer
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    BuildContext,
    BuilderSpec,
)
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.builders import governance as governance_builder
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.actions import (
    ActionService,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    RecordingActionAuditor,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.catalog.repo.memory import InMemoryCatalogRepository
from neurosphere_core.governance.policy import (
    LifecycleAuditContext,
    StoredPolicy,
    StoredViolation,
    ViolationObservation,
    dedup_key,
)
from neurosphere_core.governance.policy.models import PolicyViolationEvidence, TargetRef
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

__all__ = [
    "ADMIN",
    "ANALYST",
    "AUDITOR",
    "BASE",
    "CONTROL",
    "CONTROL_STEWARD",
    "FINANCE",
    "INVESTIGATOR",
    "OPERATIONS",
    "OPS_STEWARD",
    "STEWARD",
    "STEWARD_2",
    "SUBJECT",
    "VIEWER",
    "GovWorld",
    "Parts",
    "compose_governance",
    "draft_body",
    "pid",
    "rule",
]

STEWARD: Final = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
STEWARD_2: Final = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
ADMIN: Final = "3d4e5f6a-7b8c-4d9e-8f1a-2b3c4d5e6f70"
ANALYST: Final = "4e5f6a7b-8c9d-4e0f-9a2b-3c4d5e6f7081"
VIEWER: Final = "5f6a7b8c-9d0e-4f1a-8b3c-4d5e6f708192"
OPS_STEWARD: Final = "6a7b8c9d-0e1f-4a2b-9c4d-5e6f708192a3"
CONTROL_STEWARD: Final = "7b8c9d0e-1f2a-4b3c-8d5e-6f708192a3b4"
AUDITOR: Final = "8c9d0e1f-2a3b-4c4d-9e6f-708192a3b4c5"
INVESTIGATOR: Final = "9d0e1f2a-3b4c-4d5e-8f70-8192a3b4c5d6"

BASE: Final = "/api/v1/governance/policy"
FINANCE: Final = "commercial:contoso:neurosphere:domain:finance"
OPERATIONS: Final = "commercial:contoso:neurosphere:domain:operations"
CONTROL: Final = customer_control_domain_id("commercial", CUSTOMER)
_MEMBERSHIPS: Final = (FINANCE, OPERATIONS, CONTROL)
SUBJECT: Final = "commercial:contoso:neurosphere:agent:support-bot"
ASSET: Final = "commercial:contoso:neurosphere:grounding_source:crm-notes"


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def _policy(object_id: str, *roles: PolicyRoleAssignment) -> PrincipalPolicy:
    principal = pid(object_id)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=_MEMBERSHIPS,
        role_assignments=roles,
    )


def _policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    for principal in (
        _policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE)),
        _policy(STEWARD_2, role(Role.DOMAIN_STEWARD, FINANCE)),
        _policy(ADMIN, role(Role.ADMIN, FINANCE)),
        _policy(ANALYST, role(Role.ANALYST, FINANCE)),
        _policy(VIEWER, role(Role.VIEWER, FINANCE)),
        _policy(OPS_STEWARD, role(Role.DOMAIN_STEWARD, OPERATIONS)),
        _policy(CONTROL_STEWARD, role(Role.DOMAIN_STEWARD, CONTROL)),
        _policy(AUDITOR, role(Role.SECURITY_AUDITOR, FINANCE)),
        _policy(INVESTIGATOR, role(Role.INTERACTION_INVESTIGATOR, FINANCE, expires_in=3600)),
    ):
        repo.put_principal(principal)
    return repo


def rule(rule_id: str = "owner-needed", kind: str = "required_owner") -> dict[str, Any]:
    """One synthetic rule of ``kind`` (parameters from the PRP-99 all-kinds example)."""
    params: dict[str, dict[str, Any]] = {
        "required_owner": {"min_owners": 1, "require_active_owner": True},
        "residency": {"allowed_geographies": ["eu_eea"], "allowed_regions": ["westeurope"]},
        "content_rule": {
            "detected_categories": ["payment_card"],
            "min_count": 1,
            "parts": ["prompt"],
            "window_minutes": 60,
        },
        "budget": {
            "budget_record_id": "budget-support-monthly",
            "threshold_percent": 100,
            "on_breach": "alert",
        },
        "data_sensitivity_access": {
            "sensitivity_categories": ["pii"],
            "access": "read_or_write",
            "allowed_when": "agent_version_approved",
        },
    }
    return {
        "rule_id": rule_id,
        "kind": kind,
        "severity": None,
        "applies_to": {"entity_types": [], "tags": [], "environments": [], "entity_ids": []},
        "params": params[kind],
    }


def draft_body(policy_id: str = "support-owners", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "policy_id": policy_id,
        "display_name": "Support owners",
        "severity": "medium",
        "mode": "audit",
        "rules": [rule()],
    }
    body.update(over)
    return body


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class GovWorld:
    composed: Composed
    client: TestClient
    plane: GovernancePolicyPlane
    audit_store: InMemoryAuditStore
    hitl: HitlService
    hitl_store: InMemoryHitlStore
    intents: InMemoryIntentStore
    rechecker: GrantTablePermissionRechecker

    def auth(self, object_id: str) -> dict[str, str]:
        return self.composed.auth(object_id)

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.composed.clock(), UTC)

    def call(self, method: str, who: str | None, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if who is not None:
            headers.update(self.auth(who))
        return self.client.request(method, BASE + path, headers=headers, **kwargs)

    def operations(self) -> list[str]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[str] = []
        for chain in sorted(chains):
            docs = sorted(self.audit_store.raw_documents(chain), key=lambda d: d["sequence"])
            out.extend(str(d["operation"]) for d in docs)
        return out

    def create(self, who: str = STEWARD, domain: str = FINANCE, **over: Any) -> Any:
        return self.call("POST", who, f"/domains/{domain}/policies", json=draft_body(**over))

    async def scope_of(self, object_id: str) -> IdentityScope:
        """The server-derived scope of a principal (for direct engine calls in a test)."""
        state = self.composed.app.state.authz
        claims = await state.authenticator.authenticate(self.auth(object_id)["Authorization"])
        derived = await state.scope_source.derive(claims)
        return derived.scope

    async def publish_directly(self, scope: IdentityScope, stored: StoredPolicy) -> StoredPolicy:
        """What PRP-108's handler does after an approved intent (no route does this)."""
        outcome = await self.plane.lifecycle.publish(
            stored.policy.policy_id.root,
            stored.policy.policy_version,
            expected_etag=stored.etag,
            audit_ctx=LifecycleAuditContext(
                scope=scope,
                correlation_id="corr-test-publish",
                intent_id="00000000-0000-4000-8000-0000000000aa",
            ),
        )
        return outcome.stored

    async def violation(
        self,
        *,
        domain: str = FINANCE,
        subject: str = SUBJECT,
        policy_id: str = "support-owners",
        rule_id: str = "owner-needed",
    ) -> StoredViolation:
        observation = ViolationObservation(
            cloud="commercial",
            customer_id=CUSTOMER,
            domain_id=domain,
            policy_id=policy_id,
            policy_version=1,
            rule_id=rule_id,
            rule_kind="required_owner",
            severity="medium",
            subject=TargetRef(canonical_id=subject, entity_type="agent"),
            evidence_class="no_owner",
            evidence=(
                PolicyViolationEvidence.model_validate(
                    {
                        "evidence_kind": "catalog_entity",
                        "ref": ASSET,
                        "observed_at": "2027-01-15T08:00:00Z",
                    }
                ),
            ),
            run_id="00000000-0000-4000-8000-0000000000bb",
            correlation_id="corr-test-eval",
        )
        observed = await self.plane.violations.upsert_observed(
            dedup_key(policy_id, rule_id, subject, "no_owner"), observation, now=self.now()
        )
        return observed.stored

    def expiry(self, days: int = 30) -> str:
        return (self.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def build(cls, monkeypatch: pytest.MonkeyPatch, **env: str) -> GovWorld:
        parts = compose_governance(monkeypatch, **cast(dict[str, Any], env))
        composed, clock, audit = parts.composed, parts.clock, parts.audit
        rechecker, hitl = parts.rechecker, parts.hitl

        def now() -> datetime:
            return datetime.fromtimestamp(clock(), UTC)

        policies = parts.review_policies
        intents = InMemoryIntentStore()
        control = InMemoryExecutionControl()
        actions = ActionService(
            intents,
            auditor=RecordingActionAuditor(),
            rechecker=rechecker,
            execution_control=control,
            clock=now,
            id_factory=_ids("00000000-0000-4000-8000"),
        )
        configure_action_plane(
            composed.app,
            action_service=actions,
            intent_store=intents,
            hitl_service=hitl,
            review_policies=policies,
            write_targets=WriteTargetRegistry(),  # no platform-control target (PRP-108)
            permission_rechecker=rechecker,
            execution_control=control,
            audit_repository=audit,
            clock=now,
        )
        plane = composed.app.state.governance_policy
        assert isinstance(plane, GovernancePolicyPlane)
        return cls(
            composed=composed,
            client=composed.client(),
            plane=plane,
            audit_store=parts.audit_store,
            hitl=hitl,
            hitl_store=parts.hitl_store,
            intents=intents,
            rechecker=rechecker,
        )


@dataclass
class Parts:
    """One composition: authz, a stub data builder and the real governance builder."""

    composed: Composed
    clock: FakeClock
    audit: AuditRepository
    audit_store: InMemoryAuditStore
    hitl: HitlService
    hitl_store: InMemoryHitlStore
    review_policies: ReviewPolicyRegistry
    rechecker: GrantTablePermissionRechecker
    catalog: InMemoryCatalogRepository


def compose_governance(monkeypatch: pytest.MonkeyPatch, *, data: bool = True, **env: str) -> Parts:
    """Compose with ``NS_GOVPOLICY_BACKEND=memory`` (``env`` may override it). ``data=False``
    leaves out the stub data builder (no audit, HITL or catalog for the governance builder)."""
    runtime_helpers.configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_GOVPOLICY_BACKEND", "memory")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clock = FakeClock()
    store = InMemoryAuditStore()
    audit = AuditRepository(store)
    rechecker = GrantTablePermissionRechecker()
    for who in (STEWARD, STEWARD_2):
        for permission in ("action.propose", "action.approve", "catalog.curate"):
            rechecker.grant(pid(who), CUSTOMER, FINANCE, permission)
    policies = ReviewPolicyRegistry()
    hitl_store = InMemoryHitlStore()
    hitl = HitlService(
        hitl_store,
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        policies,
        RecheckerReviewerAuthorizer(rechecker),
    )
    catalog = InMemoryCatalogRepository()

    def build_data(ctx: BuildContext) -> None:
        ctx.app.state.audit_repository = audit
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.publish(HITL_SERVICE, hitl)
        ctx.publish(CATALOG_REPOSITORY, catalog)
        ctx.ok("audit")

    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=_policies(),
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
    )
    chain: tuple[BuilderSpec, ...] = (authz_builder.BUILDER,)
    if data:
        chain += (BuilderSpec("stub-data", ("audit",), build_data),)
    chain += (governance_builder.BUILDER,)
    composed = compose(overrides, builders=chain, clock=clock)
    return Parts(
        composed=composed,
        clock=clock,
        audit=audit,
        audit_store=store,
        hitl=hitl,
        hitl_store=hitl_store,
        review_policies=policies,
        rechecker=rechecker,
        catalog=catalog,
    )
