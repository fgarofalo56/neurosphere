"""The governance policy plane installed on the ABAC negative-suite world (PRP-105 item 7).

Builds on ``security.authz.world`` (two customers, each its own deployment with real dev-issued
tokens, server-derived scopes and the real router table) and installs, on every deployment:

* a :class:`GovernancePolicyPlane` whose STORES are shared by both deployments (one in-memory
  backend partitioned by ``customer_id``, like one Cosmos account), so a cross-customer id is a
  real record the store holds, not merely an absent one; the audit repository, HITL service and
  catalog projection target are per deployment;
* the action plane with NO write connector, so a ``governance_policy_publish`` intent is
  advisory (no platform-control target before PRP-108);
* extra principals per customer: a member with no role, an ``interaction_investigator`` (no
  governance permission), a steward whose assignment expires after 10 seconds and a steward on
  the customer-control domain only.

Synthetic data only; no network, no paid call.
"""

from __future__ import annotations

import itertools
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from neurosphere_api.actions import configure_action_plane
from neurosphere_api.governance.policy import GovernancePolicyPlane
from neurosphere_api.governance.policy.deps import configure_governance_policy
from neurosphere_api.hitl import RecheckerReviewerAuthorizer
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_core.actions import (
    ActionService,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    RecordingActionAuditor,
)
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.aggregates.subject import SubjectLookup
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.graph.query import RepositoryGraphQuery
from neurosphere_core.catalog.repo.memory import InMemoryCatalogRepository
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.governance.policy import (
    AuditDecisionRecorder,
    BindingStore,
    ExceptionRequester,
    InMemoryDocumentBackend,
    InMemoryEvaluationStatusStore,
    InMemoryExceptionStore,
    InMemoryPolicyDefinitionStore,
    InMemoryViolationStore,
    LifecycleAuditContext,
    NoopViolationEventSink,
    PolicyDecider,
    PolicyLifecycle,
    StoredPolicy,
    StoredViolation,
    ViolationObservation,
    dedup_key,
)
from neurosphere_core.governance.policy.models import (
    EvaluationStatus,
    PolicyViolationEvidence,
    RuleRunStatus,
    TargetRef,
)
from neurosphere_core.governance.policy.rules import RuleBuildContext, build_rule_registry
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.policy_eval.assembly import (
    PolicyEvalParts,
    PolicyEvalStores,
    assemble_policy_eval,
)
from neurosphere_workers.policy_eval.settings import PolicyEvalSettings

from ..authz.world import (
    AUDIENCE,
    CUSTOMERS,
    TENANTS,
    Deployment,
    Who,
    World,
    at,
    dev_issuer,
    domain_id,
    pseudonymizer,
    run,
)

__all__ = [
    "BASE",
    "EXPIRES_IN",
    "Extra",
    "GovDep",
    "GovWorld",
    "SharedStores",
    "agent",
    "assemble_worker",
    "draft_body",
    "extra_pid",
    "install",
    "rule",
    "seed_pii_reader",
    "source",
]

BASE: Final = "/api/v1/governance/policy"
FINANCE: Final = "finance"
OPERATIONS: Final = "operations"
EXPIRES_IN: Final = 10.0


class Extra:
    """Labels of the principals this module seeds beside the world's 20."""

    NO_ROLE: Final = "no-role"
    INVESTIGATOR: Final = "investigator"
    EXPIRED: Final = "expired-steward"
    CONTROL: Final = "control-steward"


def _object_id(customer: str, label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"neurosphere-govpolicy-suite/{customer}/{label}"))


def extra_pid(customer: str, label: str) -> str:
    return pseudonymizer().principal_id(
        cloud="commercial",  # type: ignore[arg-type]
        customer_id=customer,
        tenant_id=TENANTS[customer],
        object_id=_object_id(customer, label),
        kind="user",
    )


def _seed_extras(dep: Deployment) -> None:
    customer = dep.customer
    fin = domain_id(customer, FINANCE)
    control = customer_control_domain_id("commercial", customer)

    def put(label: str, memberships: tuple[str, ...], *roles: PolicyRoleAssignment) -> None:
        principal = extra_pid(customer, label)
        dep.repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(principal),
                customer_id=customer,
                principal_id=principal,
                domain_memberships=memberships,
                role_assignments=roles,
            )
        )

    def assignment(role: Role, domain: str, expires_in: float | None) -> PolicyRoleAssignment:
        return PolicyRoleAssignment(
            assignment_id=f"ra-govpolicy-{role.value}",
            role=role,
            domain_ids=(domain,),
            expires_at=None if expires_in is None else at(expires_in),
        )

    put(Extra.NO_ROLE, (fin,))
    put(Extra.INVESTIGATOR, (fin,), assignment(Role.INTERACTION_INVESTIGATOR, fin, 3600))
    put(Extra.EXPIRED, (fin,), assignment(Role.DOMAIN_STEWARD, fin, EXPIRES_IN))
    put(Extra.CONTROL, (control,), assignment(Role.DOMAIN_STEWARD, control, None))


class _NoSubjectMetrics:
    async def latest_subject_points(self, *_args: Any, **_kwargs: Any) -> SubjectLookup:
        return SubjectLookup(points={})

    async def newest_subject_points(self, *_args: Any, **_kwargs: Any) -> SubjectLookup:
        return SubjectLookup(points={})


class _NoSearch:
    async def search(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ForbiddenError("no search in this suite", reason="search_unavailable")


class _NoApiScope:
    async def get(self) -> IdentityScope:
        raise ForbiddenError("the API evaluates nothing", reason="api_scope_unavailable")


@dataclass
class SharedStores:
    """One backend for both customers (partitioned by ``customer_id``)."""

    policies: InMemoryPolicyDefinitionStore
    violations: InMemoryViolationStore
    exceptions: InMemoryExceptionStore
    bindings: BindingStore
    statuses: InMemoryEvaluationStatusStore

    @classmethod
    def build(cls) -> SharedStores:
        definitions = InMemoryDocumentBackend()
        return cls(
            policies=InMemoryPolicyDefinitionStore(definitions),
            violations=InMemoryViolationStore(),
            exceptions=InMemoryExceptionStore(),
            bindings=BindingStore(InMemoryAdminConfigRepository(cloud="commercial")),
            statuses=InMemoryEvaluationStatusStore(definitions),
        )


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class GovDep:
    """One deployment with the governance plane and the action plane installed."""

    dep: Deployment
    plane: GovernancePolicyPlane
    hitl: HitlService
    rechecker: GrantTablePermissionRechecker
    intents: InMemoryIntentStore
    catalog: InMemoryCatalogRepository

    @property
    def customer(self) -> str:
        return self.dep.customer

    def domain(self, name: str) -> str:
        return domain_id(self.customer, name)

    def bearer_extra(self, label: str, *, customer: str | None = None) -> dict[str, str]:
        """A token for an extra principal; ``customer`` mints it from ANOTHER tenant's issuer."""
        issuer_customer = customer or self.customer
        token = dev_issuer(issuer_customer).mint(
            audience=AUDIENCE,
            object_id=_object_id(issuer_customer, label),
            now=self.dep.clock.now,
        )
        return {"Authorization": f"Bearer {token}"}

    def scope_of(self, who: Who) -> IdentityScope:
        return self.dep.scope(who)

    def scope_of_extra(self, label: str) -> IdentityScope:
        header = self.bearer_extra(label)["Authorization"]
        return run(self.dep.derive_token(header.removeprefix("Bearer "))).scope

    def now(self) -> datetime:
        return self.dep.clock.dt()

    def expiry(self, days: int = 10) -> str:
        return (self.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def call(
        self, method: str, path: str, headers: dict[str, str], *, json: Any = None, **kw: Any
    ) -> Any:
        return self.dep.client.request(method, BASE + path, headers=headers, json=json, **kw)

    async def publish_directly(self, scope: IdentityScope, stored: StoredPolicy) -> StoredPolicy:
        """What PRP-108's handler does after an approved intent (no route does this)."""
        outcome = await self.plane.lifecycle.publish(
            stored.policy.policy_id.root,
            stored.policy.policy_version,
            expected_etag=stored.etag,
            audit_ctx=LifecycleAuditContext(
                scope=scope,
                correlation_id="corr-suite-publish",
                intent_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"intent/{stored.etag}")),
            ),
        )
        return outcome.stored

    async def violation(
        self,
        *,
        domain: str,
        subject: str,
        policy_id: str,
        rule_id: str = "owner-needed",
        cloud: Literal["commercial", "government"] = "commercial",
    ) -> StoredViolation:
        evidence_ref = subject.rsplit(":", 2)[0] + ":grounding_source:crm-notes"
        observation = ViolationObservation(
            cloud=cloud,
            customer_id=self.customer,
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
                        "ref": evidence_ref,
                        "observed_at": "2027-01-15T08:00:00Z",
                    }
                ),
            ),
            run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"run/{self.customer}/{domain}")),
            correlation_id="corr-suite-eval",
        )
        observed = await self.plane.violations.upsert_observed(
            dedup_key(policy_id, rule_id, subject, "no_owner"), observation, now=self.now()
        )
        return observed.stored

    async def run_status(self, domain: str) -> None:
        await self.plane.statuses.record(
            EvaluationStatus.model_validate(
                {
                    "run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"status/{domain}")),
                    "cloud": "commercial",
                    "customer_id": self.customer,
                    "domain_id": domain,
                    "trigger": "interval",
                    "state": "completed",
                    "started_at": "2027-01-15T08:00:00Z",
                    "correlation_id": "corr-suite-run",
                    "rules": [
                        RuleRunStatus(
                            policy_id="fin-owners",
                            policy_version=1,
                            rule_id="owner-needed",
                            rule_kind="required_owner",
                            outcome="complete",
                            reason_code=None,
                            subjects_evaluated=1,
                        ).model_dump()
                    ],
                }
            )
        )


def _plane(
    dep: Deployment,
    stores: SharedStores,
    catalog: InMemoryCatalogRepository,
    hitl: HitlService,
) -> GovernancePolicyPlane:
    clock = dep.clock.dt
    audit = dep.audit_repo
    registry = build_rule_registry(
        RuleBuildContext(
            catalog=catalog,
            metrics=_NoSubjectMetrics(),  # type: ignore[arg-type]
            access=AccessEngine(catalog, RepositoryGraphQuery(catalog, _NoSearch())),  # type: ignore[arg-type]
            cosmos_client=None,
            cloud="commercial",
            scope_provider=_NoApiScope(),
            clock=clock,
        )
    )
    lifecycle = PolicyLifecycle(
        stores.policies, stores.bindings, audit, registry, catalog, clock=clock
    )
    decider = PolicyDecider(
        stores.policies,
        stores.bindings,
        stores.exceptions,
        catalog=catalog,
        recorder=AuditDecisionRecorder(audit),
    )
    requester = ExceptionRequester(
        stores.violations, stores.exceptions, hitl, audit, max_days=90, clock=clock
    )
    return GovernancePolicyPlane(
        policies=stores.policies,
        violations=stores.violations,
        exceptions=stores.exceptions,
        bindings=stores.bindings,
        statuses=stores.statuses,
        lifecycle=lifecycle,
        decider=decider,
        registry=registry,
        exception_requester=requester,
        audit=audit,
        clock=clock,
        backend="memory",
        exception_max_days=90,
    )


def _install(dep: Deployment, stores: SharedStores) -> GovDep:
    audit = dep.audit_repo
    rechecker = GrantTablePermissionRechecker()
    review_policies = ReviewPolicyRegistry()
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        review_policies,
        RecheckerReviewerAuthorizer(rechecker),
    )
    catalog = InMemoryCatalogRepository()
    plane = _plane(dep, stores, catalog, hitl)
    configure_governance_policy(dep.app, plane)

    def now() -> datetime:
        return datetime.fromtimestamp(dep.clock(), UTC)

    intents = InMemoryIntentStore()
    control = InMemoryExecutionControl()
    actions = ActionService(
        intents,
        auditor=RecordingActionAuditor(),
        rechecker=rechecker,
        execution_control=control,
        clock=now,
        id_factory=_ids(str(uuid.uuid5(uuid.NAMESPACE_URL, dep.customer))[:23]),
    )
    configure_action_plane(
        dep.app,
        action_service=actions,
        intent_store=intents,
        hitl_service=hitl,
        review_policies=review_policies,
        write_targets=WriteTargetRegistry(),  # no platform-control target (PRP-108)
        permission_rechecker=rechecker,
        execution_control=control,
        audit_repository=audit,
        clock=now,
    )
    _seed_extras(dep)
    return GovDep(
        dep=dep,
        plane=plane,
        hitl=hitl,
        rechecker=rechecker,
        intents=intents,
        catalog=catalog,
    )


@dataclass
class GovWorld:
    world: World
    stores: SharedStores
    deps: dict[str, GovDep]

    def __getitem__(self, customer: str) -> GovDep:
        return self.deps[customer]


def install(world: World) -> GovWorld:
    stores = SharedStores.build()
    deps = {c: _install(world[c], stores) for c in CUSTOMERS}
    return GovWorld(world=world, stores=stores, deps=deps)


def rule(rule_id: str = "owner-needed", kind: str = "required_owner") -> dict[str, Any]:
    params: dict[str, dict[str, Any]] = {
        "required_owner": {"min_owners": 1, "require_active_owner": True},
        "registration_required": {"entity_types": ["agent"], "grace_period_hours": 24},
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


def draft_body(policy_id: str = "fin-owners", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "policy_id": policy_id,
        "display_name": "Finance owners",
        "severity": "medium",
        "mode": "audit",
        "rules": [rule()],
    }
    body.update(over)
    return body


def agent(customer: str, name: str) -> str:
    return f"commercial:{customer}:foundry:agent:{name}"


def source(customer: str, name: str) -> str:
    return f"commercial:{customer}:foundry:grounding_source:{name}"


# -- catalog and worker (the engine path that writes violations) ------------------------------

_CATALOG_EXAMPLES: Final = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "schemas"
    / "catalog"
    / "v1"
    / "examples"
    / "valid"
)


def _example(name: str) -> dict[str, Any]:
    return json.loads((_CATALOG_EXAMPLES / name).read_text(encoding="utf-8"))


def _entity(example: str, entity_id: str, customer: str, domain: str) -> dict[str, Any]:
    raw = _example(example)
    raw.update(id=entity_id, customer_id=customer, domain_id=domain, version=1, etag="caller-etag")
    return raw


async def seed_pii_reader(
    gd: GovDep, scope: IdentityScope, *, domain: str, agent_name: str, source_name: str, label: str
) -> tuple[str, str]:
    """An agent with a ``reads`` edge to a PII grounding source in ``domain``; ``label`` is put
    in every human-readable field (display names), never in an id. Returns (agent, source)."""
    customer = gd.customer
    agent_ref, source_ref = agent(customer, agent_name), source(customer, source_name)
    raw_agent = _entity("agent.minimal-and-typical.json", agent_ref, customer, domain)
    raw_agent.update(current_version_id=None, external_agent_id=None, display_name=label)
    raw_source = _entity(
        "grounding_source.sensitivity-residency.json", source_ref, customer, domain
    )
    raw_source.update(
        display_name=label, tags=[], environment="unknown", sensitivity_categories=["pii"]
    )
    raw_edge = _example("reads.asserted.json")
    raw_edge.update(
        id=f"commercial:{customer}:neurosphere:reads:r-{agent_name}-{source_name}",
        source_id=agent_ref,
        target_id=source_ref,
        customer_id=customer,
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    await gd.catalog.create_entity(scope, Agent.model_validate(raw_agent))
    await gd.catalog.create_entity(scope, GroundingSource.model_validate(raw_source))
    await gd.catalog.put_edge(scope, ReadsRelation.model_validate(raw_edge), None)
    return agent_ref, source_ref


class _Scopes:
    def __init__(self, scope: IdentityScope) -> None:
        self._scope = scope

    async def get(self) -> IdentityScope:
        return self._scope


def assemble_worker(gd: GovDep, stores: SharedStores, scope: IdentityScope) -> PolicyEvalParts:
    """The real ``policy_eval`` role over the shared stores, running as ``scope``."""
    return assemble_policy_eval(
        customer_id=gd.customer,
        cloud="commercial",
        settings=PolicyEvalSettings.model_validate({"interval_seconds": 300.0}),
        stores=PolicyEvalStores(
            policies=stores.policies,
            statuses=stores.statuses,
            violations=stores.violations,
            exceptions=stores.exceptions,
            bindings=stores.bindings,
        ),
        audit=gd.dep.audit_repo,
        hitl=gd.hitl,
        catalog=gd.catalog,
        metrics=_NoSubjectMetrics(),  # type: ignore[arg-type]
        scope_provider=_Scopes(scope),
        cosmos_client=None,
        events=NoopViolationEventSink(),
        finding_reader=None,
        clock=gd.dep.clock.dt,
        monotonic=gd.dep.clock,
    )
