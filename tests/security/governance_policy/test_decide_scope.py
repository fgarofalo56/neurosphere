"""``decide`` never describes a subject outside the caller's scope (PRP-105 item 7, criterion 7).

``decide`` has no route in this PRP (the enforcement points of PRP-108/112-114 call it in
process), so this runs at the engine level, but over the negative-suite world: REAL
server-derived scopes from dev-issued tokens, policies published through ``PolicyLifecycle``,
bindings moved to ``enforce`` only through ``BindingStore.set_mode`` and the decider the API
builder installs (with its audit recorder). Complements the core unit tests with fabricated
scopes (``packages/core/tests/governance_policy/test_decide_scope.py``).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from typing import Any, Final

import pytest
from neurosphere_core.auth.scope import Role
from neurosphere_core.governance.policy.models import PolicyDecisionRequest
from neurosphere_core.scope import IdentityScope

from ..authz.world import Who, build_world, run
from .govpolicy_world import GovDep, GovWorld, agent, install, rule, seed_pii_reader, source

FIN: Final = "finance"
OPS: Final = "operations"
FIN_VIEWER: Final = Who("contoso", FIN, Role.VIEWER)
FIN_STEWARD: Final = Who("contoso", FIN, Role.DOMAIN_STEWARD)
OPS_STEWARD: Final = Who("contoso", OPS, Role.DOMAIN_STEWARD)
HIDDEN_AGENT: Final = agent("contoso", "ops-bot")
HIDDEN_SOURCE: Final = source("contoso", "ops-ledger")
GHOST_AGENT: Final = agent("contoso", "ghost-bot")
GHOST_SOURCE: Final = source("contoso", "ghost-ledger")
HIDDEN_LABEL: Final = "Pangolin Operations Display 4410"


def _request(point: str, **fields: Any) -> PolicyDecisionRequest:
    body: dict[str, Any] = {"schema_version": "1.2.0", "decision_point": point}
    body.update(copy.deepcopy(fields))
    return PolicyDecisionRequest.model_validate(body)


async def _publish(
    gd: GovDep, scope: IdentityScope, domain: str, policy_id: str, kind: str
) -> None:
    draft = gd.plane.policies.create_draft(
        {
            "schema_version": "1.2.0",
            "policy_id": policy_id,
            "policy_version": 1,
            "previous_version": None,
            "cloud": "commercial",
            "customer_id": gd.customer,
            "domain_id": domain,
            "display_name": "Synthetic",
            "document_url": None,
            "status": "draft",
            "mode": "audit",
            "severity": "high",
            "rules": [rule(f"r-{kind.replace('_', '-')}", kind)],
            "created_by": scope.to_contract().principal.principal_id.root,
            "created_at": "2027-01-15T08:00:00Z",
            "published_at": None,
            "published_intent_id": None,
            "published_audit_id": None,
        }
    )
    stored = await draft
    await gd.publish_directly(scope, stored)
    for binding in await gd.plane.bindings.list(gd.customer, policy_id=policy_id):
        await gd.plane.bindings.set_mode(
            gd.customer,
            binding.binding.binding_id.root,
            "enforce",
            if_match=binding.etag,
            updated_by=scope.to_contract().principal.principal_id.root,
        )


@pytest.fixture
def gw() -> Iterator[GovWorld]:
    world = install(build_world())
    gd = world["contoso"]
    ops_scope = gd.scope_of(OPS_STEWARD)
    run(
        seed_pii_reader(
            gd,
            ops_scope,
            domain=gd.domain(OPS),
            agent_name="ops-bot",
            source_name="ops-ledger",
            label=HIDDEN_LABEL,
        )
    )
    fin_scope = gd.scope_of(FIN_STEWARD)
    run(_publish(gd, fin_scope, gd.domain(FIN), "fin-registration", "registration_required"))
    run(_publish(gd, fin_scope, gd.domain(FIN), "fin-pii", "data_sensitivity_access"))
    run(_publish(gd, ops_scope, gd.domain(OPS), "ops-registration", "registration_required"))
    yield world


def _decide(gd: GovDep, who: Who | GovDep, request: PolicyDecisionRequest) -> str:
    if isinstance(who, Who):
        scope = gd.scope_of(who)
    else:  # another deployment's steward: that customer's own derived scope
        scope = who.scope_of(Who(who.customer, FIN, Role.DOMAIN_STEWARD))
    response = run(gd.plane.decider.decide(scope, request, now=gd.now()))
    return response.model_dump_json().replace(response.decision_id.root, "<decision>")


def _audit_text(gd: GovDep) -> str:
    store = gd.dep.audit_store
    chains = {chain for (chain, _doc) in store._docs}  # pyright: ignore[reportPrivateUsage]
    return json.dumps([d for c in sorted(chains) for d in store.raw_documents(c)])


def test_a_subject_in_an_unseen_domain_reads_exactly_like_a_missing_one(gw: GovWorld) -> None:
    gd = gw["contoso"]
    hidden = _decide(
        gd, FIN_VIEWER, _request("registration", operation="register", agent_id=HIDDEN_AGENT)
    )
    missing = _decide(
        gd, FIN_VIEWER, _request("registration", operation="register", agent_id=GHOST_AGENT)
    )
    assert HIDDEN_AGENT not in hidden
    assert hidden == missing.replace(GHOST_AGENT, HIDDEN_AGENT)
    for text in (hidden, _audit_text(gd)):
        assert HIDDEN_AGENT not in text
        assert HIDDEN_LABEL not in text


def test_an_asset_in_an_unseen_domain_is_never_described(gw: GovWorld) -> None:
    gd = gw["contoso"]
    fields = {"operation": "data_access", "agent_id": GHOST_AGENT, "access": "read"}
    hidden = _decide(
        gd, FIN_VIEWER, _request("tool_call", **fields, data_asset_ids=[HIDDEN_SOURCE])
    )
    missing = _decide(
        gd, FIN_VIEWER, _request("tool_call", **fields, data_asset_ids=[GHOST_SOURCE])
    )
    assert hidden == missing
    for text in (hidden, _audit_text(gd)):
        assert HIDDEN_SOURCE not in text
        assert HIDDEN_LABEL not in text
        assert "ops-ledger" not in text


def test_a_policy_outside_the_scope_is_never_applied_or_named(gw: GovWorld) -> None:
    gd = gw["contoso"]
    request = _request("registration", operation="register", agent_id=GHOST_AGENT)
    fin_view = _decide(gd, FIN_VIEWER, request)
    assert "ops-registration" not in fin_view
    assert "fin-registration" in fin_view, "the in-scope enforce policy did match"
    ops_view = _decide(gd, OPS_STEWARD, request)
    assert "fin-registration" not in ops_view
    assert "fin-pii" not in ops_view


def test_another_customers_scope_sees_none_of_it(gw: GovWorld) -> None:
    contoso, fabrikam = gw["contoso"], gw["fabrikam"]
    request = _request("registration", operation="register", agent_id=HIDDEN_AGENT)
    answer = json.loads(_decide(contoso, fabrikam, request))
    assert answer["effect"] == "allow"
    assert answer["matches"] == []
    text = json.dumps(answer)
    for name in ("fin-registration", "ops-registration", "fin-pii", HIDDEN_AGENT, HIDDEN_LABEL):
        assert name not in text
