"""Harness for the ``PolicyDecider`` tests (PRP-105 item 4; synthetic data only, no I/O).

Policies are published through the real :class:`PolicyLifecycle` of the item-3 engine harness
(bindings start in ``audit``), modes change through ``BindingStore.set_mode`` (the one path that
sets ``enforce``), and exceptions are approved through the exception store, so the decider reads
exactly what the engine writes.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from neurosphere_contracts.admin.v1.system_setting import EnforcementSetting
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.governance.policy import (
    DecisionAuditRecorder,
    PolicyDecider,
    PolicyDecision,
    StoredBinding,
)
from neurosphere_core.governance.policy.models import (
    PolicyDecisionRequest,
    PolicyException,
)
from neurosphere_core.governance.policy.rules import RuleOutcome
from neurosphere_core.scope import IdentityScope

from .engine_helpers import (
    CONTROL,
    DOMAIN_A,
    DOMAIN_B,
    WORKER_ID,
    CannedEvaluator,
    Engine,
    build_engine,
    policy_draft,
    rule,
)
from .rules.rules_helpers import (
    NOW,
    agent,
    agent_id,
    agent_version,
    deployment,
    deployment_id,
    dom,
    grounding_source,
    owned_by,
    owner,
    owner_id,
    seed,
    source_id,
    version_id,
)
from .rules.rules_helpers import make_scope as catalog_scope

DOMAIN_HIDDEN = dom("hidden")
READER = agent_id("reader")
READER_V1 = version_id("reader-v1")
APPROVED_AGENT = agent_id("approved")
APPROVED_V1 = version_id("approved-v1")
PII_SOURCE = source_id("customers")
PLAIN_SOURCE = source_id("public-docs")
HIDDEN_SOURCE = source_id("hidden-ledger")
HIDDEN_AGENT = agent_id("hidden-bot")
GHOST_AGENT = agent_id("ghost")
GPT = deployment_id("gpt")
EXC_SEQ = iter(range(1, 10_000))

#: rule kind -> (decision point, params, request fields that break the rule).
BREACH: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {
    "model_allow_list": (
        "gateway",
        {"allowed_models": [{"model_name": "gpt-4o-mini", "model_version": None}]},
        {
            "operation": "model_call",
            "agent_id": READER,
            "model": {"model_name": "gpt-4o", "model_version": None, "deployment_id": None},
        },
    ),
    "data_sensitivity_access": (
        "tool_call",
        {
            "sensitivity_categories": ["pii"],
            "access": "read",
            "allowed_when": "agent_version_approved",
        },
        {
            "operation": "data_access",
            "agent_id": READER,
            "data_asset_ids": [PII_SOURCE],
            "access": "read",
        },
    ),
    "residency": (
        "gateway",
        {"allowed_geographies": [], "allowed_regions": ["eastus"]},
        {"operation": "data_access", "agent_id": READER, "data_asset_ids": [PII_SOURCE]},
    ),
    "registration_required": (
        "registration",
        {"entity_types": ["agent"], "grace_period_hours": 24},
        {"operation": "register", "agent_id": GHOST_AGENT},
    ),
    "required_approval": (
        "registration",
        {"entity_types": ["agent_version"], "block_activation": True},
        {"operation": "register", "agent_version_id": READER_V1},
    ),
    "required_owner": (
        "registration",
        {"min_owners": 1, "require_active_owner": True},
        {"operation": "register", "agent_id": READER},
    ),
}

#: rule kind -> request fields that comply with the BREACH params (same point).
COMPLY: dict[str, dict[str, Any]] = {
    "model_allow_list": {
        "operation": "model_call",
        "agent_id": READER,
        "model": {
            "model_name": "gpt-4o-mini",
            "model_version": "2024-07-18",
            "deployment_id": None,
        },
    },
    "data_sensitivity_access": {
        "operation": "data_access",
        "agent_id": APPROVED_AGENT,
        "data_asset_ids": [PII_SOURCE],
        "access": "read",
    },
    "residency": {"operation": "data_access", "agent_id": READER, "data_asset_ids": [PLAIN_SOURCE]},
    "registration_required": {"operation": "register", "agent_id": READER},
    "required_approval": {"operation": "register", "agent_version_id": APPROVED_V1},
    "required_owner": {"operation": "register", "agent_id": APPROVED_AGENT},
}


def scope_for(
    allowed: Sequence[str],
    *,
    customer: str = "acme",
    cloud: str = "commercial",
    hex_char: str = "e",
) -> IdentityScope:
    """A server-derived scope fixture (viewer in ``allowed``)."""
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer,
        "principal": {
            "principal_id": f"{cloud}:{customer}:entra:person:p-{hex_char * 64}",
            "principal_pseudonym": f"p-{hex_char * 64}",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": list(allowed)}] if allowed else [],
        "allowed_domains": list(allowed),
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(hex_char.encode()).hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


SCOPE_A = scope_for([DOMAIN_A])
SCOPE_AB = scope_for([DOMAIN_A, DOMAIN_B])


def request(point: str, **fields: Any) -> PolicyDecisionRequest:
    body: dict[str, Any] = {"schema_version": "1.2.0", "decision_point": point}
    body.update(copy.deepcopy(fields))
    return PolicyDecisionRequest.model_validate(body)


async def world() -> Engine:
    """Catalog: ``reader`` (no owner, unapproved v1), ``approved`` (approved current version),
    PII source in westeurope, a plain source in eastus, and a PII source and an agent in a
    domain no test caller scope covers."""
    engine = await build_engine()
    repo = engine.catalog
    await seed(
        repo,
        agent("approved", current_version_id=APPROVED_V1),
        agent_version("reader-v1", "reader", state="pending"),
        agent_version("approved-v1", "approved", state="approved"),
        grounding_source("public-docs", sensitivity_categories=[], residency_region="eastus"),
        deployment("gpt"),
        owner("alice"),
        owned_by("o-approved-alice", APPROVED_AGENT, owner_id("alice")),
    )
    wide = catalog_scope("a", "b", "hidden")
    await repo.create_entity(
        wide, grounding_source("hidden-ledger", "hidden", sensitivity_categories=["pii"])
    )
    await repo.create_entity(wide, agent("hidden-bot", "hidden"))
    for kind in ("model_allow_list", "residency", "required_owner", "required_approval"):
        engine.registry.register(CannedEvaluator(kind, RuleOutcome(kind=kind)))
    engine.registry.register(
        CannedEvaluator("registration_required", RuleOutcome(kind="registration_required"))
    )
    return engine


async def publish(
    engine: Engine,
    kind: str,
    *,
    policy_id: str | None = None,
    domain: str = DOMAIN_A,
    params: dict[str, Any] | None = None,
    applies_to: dict[str, Any] | None = None,
) -> str:
    """Publish a one-rule policy of ``kind`` (rule id ``r-<kind>``); returns the policy id."""
    pid = policy_id or kind.replace("_", "-")
    body = rule(f"r-{kind.replace('_', '-')}", kind, params or BREACH[kind][1])
    if applies_to:
        body["applies_to"].update(applies_to)
    outcome = await engine.publish(policy_draft(pid, domain=domain, rules=[body]))
    assert outcome.stored.policy.status == "published"
    return pid


async def bindings_of(engine: Engine, policy_id: str, point: str) -> list[StoredBinding]:
    return await engine.bindings.list("acme", policy_id=policy_id, point=point)


async def set_mode(engine: Engine, policy_id: str, point: str, mode: str) -> None:
    for stored in await bindings_of(engine, policy_id, point):
        await engine.bindings.set_mode(
            "acme",
            stored.binding.binding_id.root,
            mode,  # type: ignore[arg-type]
            if_match=stored.etag,
            updated_by=WORKER_ID,
        )


async def approve_exception(
    engine: Engine,
    *,
    policy_id: str,
    rule_id: str,
    subject: str,
    domain: str = DOMAIN_A,
    expires_at: str = "2026-12-20T09:00:00Z",
    requested_at: str = "2026-10-01T09:00:00Z",
) -> str:
    """An approved exception for (policy, rule, subject); returns its id."""
    exception_id = f"00000000-0000-4000-8000-{next(EXC_SEQ):012d}"
    stored = await engine.exceptions.request(
        PolicyException.model_validate(
            {
                "schema_version": "1.2.0",
                "exception_id": exception_id,
                "cloud": "commercial",
                "customer_id": "acme",
                "domain_id": domain,
                "policy_id": policy_id,
                "rule_id": rule_id,
                "subject": {"canonical_id": subject, "entity_type": subject.split(":")[3]},
                "violation_id": None,
                "status": "requested",
                "reason_code": "migration_in_progress",
                "requested_by": WORKER_ID,
                "requested_at": requested_at,
                "review_item_id": "hitl-item-1",
                "expires_at": expires_at,
            }
        )
    )
    await engine.exceptions.set_state(
        "acme",
        domain,
        exception_id,
        "approved",
        if_match=stored.etag,
        decided_by=WORKER_ID,
        decided_at=NOW,
    )
    return exception_id


class Settings:
    """A settable ``EnforcementSetting`` provider."""

    def __init__(self, ttl: int = 60) -> None:
        self.ttl = ttl

    def __call__(self) -> EnforcementSetting:
        return EnforcementSetting(decision_cache_ttl_seconds=self.ttl)


class Recorder:
    """``DecisionAuditRecorder`` that keeps every decision it is handed."""

    def __init__(self) -> None:
        self.decisions: list[PolicyDecision] = []

    async def record(
        self, scope: IdentityScope, request: PolicyDecisionRequest, decision: PolicyDecision
    ) -> None:
        self.decisions.append(decision)


_WRITE_PREFIXES = (
    "create",
    "put",
    "update",
    "replace",
    "delete",
    "deprecate",
    "upsert",
    "set_",
    "request",
    "mark_",
    "ensure",
    "resolve",
    "record",
    "append",
)


class Spy:
    """Proxy that records every attribute (method) name used on the wrapped store."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []
        self.fail = False

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        async def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if self.fail:
                raise ConnectionError("store down")
            return await getattr(self._inner, name)(*args, **kwargs)

        return call

    def writes(self) -> list[str]:
        return [c for c in self.calls if c.startswith(_WRITE_PREFIXES)]


def decider(
    engine: Engine,
    *,
    settings: Settings | None = None,
    recorder: DecisionAuditRecorder | None = None,
    catalog: bool = True,
    spies: tuple[Spy, Spy, Spy] | None = None,
) -> PolicyDecider:
    policies, bindings, exceptions = spies or (
        engine.policies,
        engine.bindings,
        engine.exceptions,
    )
    return PolicyDecider(
        policies,  # type: ignore[arg-type]
        bindings,  # type: ignore[arg-type]
        exceptions,  # type: ignore[arg-type]
        catalog=engine.catalog if catalog else None,
        settings=settings or Settings(),
        recorder=recorder,
    )


def spies(engine: Engine) -> tuple[Spy, Spy, Spy]:
    return Spy(engine.policies), Spy(engine.bindings), Spy(engine.exceptions)


__all__ = [
    "APPROVED_AGENT",
    "APPROVED_V1",
    "BREACH",
    "COMPLY",
    "CONTROL",
    "DOMAIN_A",
    "DOMAIN_B",
    "DOMAIN_HIDDEN",
    "GHOST_AGENT",
    "GPT",
    "HIDDEN_AGENT",
    "HIDDEN_SOURCE",
    "NOW",
    "PII_SOURCE",
    "PLAIN_SOURCE",
    "READER",
    "READER_V1",
    "SCOPE_A",
    "SCOPE_AB",
    "Recorder",
    "Settings",
    "Spy",
    "approve_exception",
    "at",
    "bindings_of",
    "decider",
    "publish",
    "request",
    "scope_for",
    "set_mode",
    "spies",
    "world",
]


def at(seconds: float) -> datetime:
    """``NOW`` plus ``seconds``."""
    return NOW + timedelta(seconds=seconds)
