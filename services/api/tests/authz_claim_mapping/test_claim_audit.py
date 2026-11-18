"""PRP-138 item 4: ``ClaimGrantAuditObserver`` and ``ClaimMappingStats``.

One ``identity.claim_role_applied`` record per token per process, on the customer control
domain's chain, metadata only (no token, claim list, group object id or name); a failed or
impossible write raises (the deriver turns it into 503 ``audit_write_failed``) and is retried.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    AUDIENCE,
    BOB,
    CUSTOMER,
    TENANT,
    FakeClock,
    at,
    dev_issuer,
    make_validator,
    pseudonymizer,
)
from neurosphere_api.authz import (
    CLAIM_ROLE_APPLIED_OPERATION,
    ClaimGrantAuditObserver,
    ClaimMappingStats,
)
from neurosphere_api.authz.claim_audit import claim_role_applied_detail
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.audit.content_guard import GUID, find_sensitive_content
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    ClaimGrant,
    InMemoryPolicyRepository,
    NoRevocationCheck,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    customer_control_domain_id,
    parse_claim_role_mapping,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

CONTROL = customer_control_domain_id("commercial", CUSTOMER)
CHAIN = domain_audit_chain_id(CUSTOMER, CONTROL)
FINANCE = "commercial:contoso:catalog:domain:finance"
GROUP = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
MAPPING_DOC: dict[str, Any] = {
    "tenant_id": TENANT,
    "audience": AUDIENCE,
    "entries": [
        {
            "id": "ns-admins",
            "claim": "roles",
            "value": "admin",
            "role": "admin",
            "domains": "all",
            "customer_control": True,
        },
        {
            "id": "ns-group-viewers",
            "claim": "groups",
            "value": GROUP,
            "role": "viewer",
            "domains": [FINANCE],
            "customer_control": False,
        },
    ],
}


class _Directory:
    def __init__(self, *domains: str) -> None:
        self.domains = domains

    async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
        return self.domains


class FailingRepository:
    """Audit repository whose append fails ``failures`` times, then delegates."""

    def __init__(self, inner: AuditRepository, failures: int) -> None:
        self.inner = inner
        self.failures = failures
        self.calls = 0

    async def append(self, chain_id: str, draft: Any) -> AuditRecord:
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise DependencyTransientError("down", reason="audit_write_failed")
        return await self.inner.append(chain_id, draft)


def _repo() -> AuditRepository:
    return AuditRepository(InMemoryAuditStore())


def _records(repo: AuditRepository) -> list[AuditRecord]:
    return asyncio.run(repo.read_range(CHAIN, limit=100))


def _claims(clock: FakeClock, object_id: str = ALICE, **mint: Any) -> VerifiedClaims:
    mint.setdefault("roles", ["admin"])
    mint.setdefault("scopes", ["access_as_user"])
    token = dev_issuer().mint(audience=AUDIENCE, object_id=object_id, now=clock.now, **mint)
    return asyncio.run(make_validator(clock).authenticate(f"Bearer {token}"))


def _deriver(clock: FakeClock, observer: Any, *domains: str) -> ScopeDeriver:
    mapping = parse_claim_role_mapping(json.dumps(MAPPING_DOC))
    config = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER
    )
    return ScopeDeriver(
        config,
        policy_repository=InMemoryPolicyRepository(),
        pseudonymizer=pseudonymizer(),
        revocation_checker=NoRevocationCheck(),
        clock=clock,
        claim_mapping=mapping,
        domain_directory=_Directory(*domains),
        claim_grant_observer=observer,
        allow_dev_issuer=True,
    )


def _scope(clock: FakeClock, object_id: str = ALICE) -> IdentityScope:
    deriver = _deriver(clock, None)
    return asyncio.run(deriver.derive(_claims(clock, object_id))).scope


def _grant(entry_id: str = "ns-admins", **values: Any) -> ClaimGrant:
    fields: dict[str, Any] = {
        "entry_id": entry_id,
        "claim": "roles",
        "role": Role.ADMIN,
        "domain_ids": (CONTROL,),
        "customer_control": True,
        "expires_at": at(3600),
        **values,
    }
    return ClaimGrant(**fields)


def _notify(
    observer: ClaimGrantAuditObserver,
    scope: IdentityScope,
    grants: tuple[ClaimGrant, ...],
    issued_at: datetime | None = None,
) -> None:
    asyncio.run(observer.on_claim_grants(scope, grants, issued_at or at(0), at(3600)))


# --------------------------------------------------------------------------- chain proof


def test_control_domain_encodes_to_an_audit_chain_and_accepts_an_append() -> None:
    """REQUIRED PROOF (PRP-138 gotcha): ``customer-control`` encodes and can be appended to."""
    assert CONTROL == "commercial:contoso:neurosphere:domain:customer-control"
    chain = domain_audit_chain_id(CUSTOMER, CONTROL)
    assert chain.startswith(f"{CUSTOMER}.")
    assert "customer-control" in chain
    repo = _repo()
    observer = ClaimGrantAuditObserver(lambda: repo)
    _notify(observer, _scope(FakeClock()), (_grant(),))
    [record] = asyncio.run(repo.read_range(chain, limit=10))
    assert record.chain_id == chain
    assert record.sequence == 0
    assert asyncio.run(repo.verify(chain)).ok is True


def test_government_control_domain_encodes_too() -> None:
    gov = customer_control_domain_id("government", CUSTOMER)
    # The chain name carries no cloud (one deployment is one cloud): same chain id, no error.
    assert domain_audit_chain_id(CUSTOMER, gov) == CHAIN


# --------------------------------------------------------------------------- record content


def test_record_carries_metadata_only() -> None:
    clock = FakeClock()
    repo = _repo()
    scope = _scope(clock)
    observer = ClaimGrantAuditObserver(lambda: repo)
    grants = (
        _grant(),
        _grant(
            "ns-group-viewers",
            claim="groups",
            role=Role.VIEWER,
            domain_ids=(FINANCE,),
            customer_control=False,
        ),
    )
    _notify(observer, scope, grants, at(0))
    [record] = _records(repo)
    contract = scope.to_contract()
    assert record.operation == CLAIM_ROLE_APPLIED_OPERATION
    assert record.kind == "after"
    assert record.actor.principal_pseudonym == contract.principal.principal_pseudonym
    assert record.scope_hash.root == contract.scope_hash
    assert record.subject is not None
    assert record.subject.target.canonical_id == CONTROL
    assert record.outcome is not None
    detail = record.outcome.detail
    assert detail == (
        f"iat={int(at(0).timestamp())}:exp={int(at(3600).timestamp())}:domains=2"
        ":claims=groups.roles:roles=admin.viewer:entries=ns-admins.ns-group-viewers"
    )
    dumped = json.dumps(record.model_dump(mode="json"))
    for forbidden in (GROUP, ALICE, TENANT, "eyJ", "Bearer", "admin@"):
        assert forbidden not in dumped
    body = record.model_dump(mode="json")
    body.pop("audit_id")  # a server-assigned UUID; allowed by the guard
    assert not GUID.search(json.dumps(body))
    assert find_sensitive_content(record.model_dump(mode="json")) == []


def test_detail_stays_within_the_guard_pattern_when_entries_do_not_fit() -> None:
    long_ids = [f"entry-{i:02d}-" + "x" * 50 for i in range(6)]
    grants = tuple(_grant(entry_id) for entry_id in long_ids)
    detail = claim_role_applied_detail(grants, at(0), at(3600))
    assert len(detail) <= 128
    assert ":more=" in detail
    assert find_sensitive_content({"outcome": {"detail": detail}}) == []


# --------------------------------------------------------------------------- once per token


def test_once_per_token_then_again_for_a_second_token() -> None:
    clock = FakeClock()
    repo = _repo()
    scope = _scope(clock)
    observer = ClaimGrantAuditObserver(lambda: repo)
    _notify(observer, scope, (_grant(),), at(0))
    _notify(observer, scope, (_grant(),), at(0))  # same token: nothing new
    assert len(_records(repo)) == 1
    _notify(observer, scope, (_grant(),), at(60))  # a new token (another issued-at)
    assert len(_records(repo)) == 2
    _notify(observer, _scope(clock, BOB), (_grant(),), at(60))  # another principal
    assert len(_records(repo)) == 3
    _notify(observer, scope, (_grant(), _grant("ns-other")), at(60))  # other entries
    assert len(_records(repo)) == 4


def test_derivations_through_the_deriver_audit_once_per_token() -> None:
    clock = FakeClock()
    repo = _repo()
    stats = ClaimMappingStats(parse_claim_role_mapping(json.dumps(MAPPING_DOC)))  # type: ignore[arg-type]
    observer = ClaimGrantAuditObserver(lambda: repo, stats=stats)
    deriver = _deriver(clock, observer, FINANCE)
    claims = _claims(clock)
    first = asyncio.run(deriver.derive(claims))
    second = asyncio.run(deriver.derive(claims))
    assert [g.entry_id for g in first.claim_grants] == ["ns-admins"]
    assert first.scope.scope_hash == second.scope.scope_hash
    [record] = _records(repo)
    assert record.outcome is not None
    assert ":domains=2:" in (record.outcome.detail or "")  # control + finance
    clock.advance(30)
    asyncio.run(deriver.derive(_claims(clock)))  # a fresh token
    assert len(_records(repo)) == 2
    assert stats.snapshot()[ClaimMappingStats.APPLIED] == 3


def test_failed_append_raises_and_is_retried_on_the_next_request() -> None:
    clock = FakeClock()
    inner = _repo()
    failing = FailingRepository(inner, failures=1)
    observer = ClaimGrantAuditObserver(lambda: failing)  # type: ignore[arg-type, return-value]
    scope = _scope(clock)
    with pytest.raises(DependencyTransientError):
        _notify(observer, scope, (_grant(),), at(0))
    assert observer.remembered == 0
    _notify(observer, scope, (_grant(),), at(0))  # same token: written now
    assert failing.calls == 2
    assert len(_records(inner)) == 1


def test_failed_append_through_the_deriver_denies_with_audit_write_failed() -> None:
    clock = FakeClock()
    failing = FailingRepository(_repo(), failures=5)
    observer = ClaimGrantAuditObserver(lambda: failing)  # type: ignore[arg-type, return-value]
    deriver = _deriver(clock, observer)
    with pytest.raises(DependencyTransientError) as caught:
        asyncio.run(deriver.derive(_claims(clock)))
    assert caught.value.reason == "audit_write_failed"


def test_missing_repository_raises() -> None:
    observer = ClaimGrantAuditObserver(lambda: None)
    with pytest.raises(DependencyTransientError) as caught:
        _notify(observer, _scope(FakeClock()), (_grant(),))
    assert caught.value.reason == "audit_store_unconfigured"
    assert observer.remembered == 0


def test_repository_is_resolved_per_call() -> None:
    holder: dict[str, AuditRepository] = {}
    observer = ClaimGrantAuditObserver(lambda: holder.get("repo"))
    scope = _scope(FakeClock())
    with pytest.raises(DependencyTransientError):
        _notify(observer, scope, (_grant(),))
    holder["repo"] = _repo()
    _notify(observer, scope, (_grant(),))
    assert len(_records(holder["repo"])) == 1


def test_no_grants_writes_nothing() -> None:
    repo = _repo()
    observer = ClaimGrantAuditObserver(lambda: repo)
    _notify(observer, _scope(FakeClock()), ())
    assert _records(repo) == []


def test_cache_is_bounded_and_evicts_the_oldest() -> None:
    repo = _repo()
    observer = ClaimGrantAuditObserver(lambda: repo, max_tokens=3)
    scope = _scope(FakeClock())
    for second in range(5):
        _notify(observer, scope, (_grant(),), at(second))
    assert observer.remembered == 3
    assert len(_records(repo)) == 5
    _notify(observer, scope, (_grant(),), at(4))  # still remembered
    assert len(_records(repo)) == 5
    _notify(observer, scope, (_grant(),), at(0))  # evicted: written again
    assert len(_records(repo)) == 6


def test_default_cache_bound_is_ten_thousand() -> None:
    from neurosphere_api.authz.claim_audit import DEFAULT_SEEN_TOKENS

    assert DEFAULT_SEEN_TOKENS == 10_000
    with pytest.raises(ValueError, match="max_tokens"):
        ClaimGrantAuditObserver(lambda: None, max_tokens=0)


# --------------------------------------------------------------------------- counters


def test_stats_count_overage_and_unmatched_values_only() -> None:
    clock = FakeClock()
    mapping = parse_claim_role_mapping(json.dumps(MAPPING_DOC))
    assert mapping is not None
    stats = ClaimMappingStats(mapping)
    stats.observe_claims(_claims(clock, roles=["admin", "reader", "writer"]))
    assert stats.snapshot() == {ClaimMappingStats.UNMATCHED_VALUES: 2}
    stats.observe_claims(
        _claims(clock, extra={"groups": [GROUP, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]})
    )
    assert stats.snapshot()[ClaimMappingStats.UNMATCHED_VALUES] == 3
    stats.observe_claims(_claims(clock, extra={"hasgroups": True}))
    snapshot = stats.snapshot()
    assert snapshot[ClaimMappingStats.GROUPS_OVERAGE] == 1
    assert set(snapshot) <= {
        ClaimMappingStats.APPLIED,
        ClaimMappingStats.GROUPS_OVERAGE,
        ClaimMappingStats.UNMATCHED_VALUES,
    }
    for key in snapshot:
        assert GROUP not in key and "admin" not in key


def test_stats_ignore_tokens_not_bound_to_the_mapping() -> None:
    clock = FakeClock()
    doc = {**MAPPING_DOC, "audience": "api://another-api"}
    mapping = parse_claim_role_mapping(json.dumps(doc))
    assert mapping is not None
    stats = ClaimMappingStats(mapping)
    stats.observe_claims(_claims(clock, roles=["reader"], extra={"hasgroups": True}))
    stats.observe_claims(object())  # not verified claims: ignored
    assert stats.snapshot() == {}
