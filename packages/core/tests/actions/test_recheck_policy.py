"""PolicyPermissionRechecker: current policy, revocation first, fail closed, parity with permits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_core.actions import (
    ActionService,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    PermissionRechecker,
    RecordingActionAuditor,
)
from neurosphere_core.actions.recheck import PolicyPermissionRechecker
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationEntry,
)
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    Permission,
    PolicyGrant,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    permits,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, ForbiddenError

from .action_helpers import FakeClock, caller, passed, request

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
ADMIN_OBJECT_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CUSTOMER = "contoso"
RETAIL = "commercial:contoso:catalog:domain:retail"
FINANCE = "commercial:contoso:catalog:domain:finance"
HR = "commercial:contoso:catalog:domain:hr"
OTHER_CUSTOMER = "commercial:fabrikam:catalog:domain:retail"
GOV_RETAIL = "government:contoso:catalog:domain:retail"
AGENT = "commercial:contoso:foundry:agent:support-bot"
T0 = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
_PSEUDONYMIZER = PrincipalPseudonymizer(
    PseudonymKey(
        bytes(range(32)),
        reference="https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key",
    )
)


def principal(object_id: str = OBJECT_ID) -> str:
    return f"commercial:{CUSTOMER}:entra:person:{_PSEUDONYMIZER.pseudonym(TENANT, object_id)}"


MAKER = principal()
ADMIN = principal(ADMIN_OBJECT_ID)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def epoch(self) -> float:
        return self.now.timestamp()


def assignment(role: Role, *domains: str, expires_in: float | None = None) -> PolicyRoleAssignment:
    return PolicyRoleAssignment(
        assignment_id=f"ra-{role.value}-{len(domains)}",
        role=role,
        domain_ids=domains,
        expires_at=None if expires_in is None else T0 + timedelta(seconds=expires_in),
    )


def policy(
    *roles: PolicyRoleAssignment,
    memberships: tuple[str, ...] = (RETAIL, FINANCE),
    grants: tuple[PolicyGrant, ...] = (),
    principal_id: str = MAKER,
) -> PrincipalPolicy:
    return PrincipalPolicy(
        id=principal_document_id(principal_id),
        customer_id=CUSTOMER,
        principal_id=principal_id,
        domain_memberships=memberships,
        role_assignments=roles,
        grants=grants,
    )


def repo(doc: PrincipalPolicy | None = None, *, head: bool = True) -> InMemoryPolicyRepository:
    repository = InMemoryPolicyRepository()
    if head:
        repository.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="2026.10.20-1"))
    if doc is not None:
        repository.put_principal(doc)
    return repository


def rechecker(
    repository: InMemoryPolicyRepository,
    *,
    revocation: Any = None,
    clock: Clock | None = None,
    **kwargs: Any,
) -> PolicyPermissionRechecker:
    return PolicyPermissionRechecker(
        cloud=CloudName.COMMERCIAL,
        policy_repository=repository,
        revocation_checker=revocation or NoRevocationCheck(),
        clock=clock or Clock(),
        **kwargs,
    )


def revocations(clock: Clock) -> tuple[InMemoryRevocationStore, CachedRevocationChecker]:
    store = InMemoryRevocationStore(clock=clock.epoch)
    return store, CachedRevocationChecker(store, clock=clock.epoch)


async def revoke(store: InMemoryRevocationStore, principal_id: str, at: datetime) -> None:
    await store.put(
        RevocationEntry(
            principal_id=principal_id, revoked_at=at, reason="offboarded", revoked_by=ADMIN
        )
    )


# -- grants ------------------------------------------------------------------------------------


async def test_is_a_permission_rechecker() -> None:
    assert isinstance(rechecker(repo()), PermissionRechecker)


async def test_steward_holds_execute_on_assigned_domain_only() -> None:
    checker = rechecker(repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL))))
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.approve") is True
    assert await checker.check(MAKER, CUSTOMER, FINANCE, "action.execute") is False


async def test_analyst_cannot_execute_and_admin_has_no_bypass() -> None:
    doc = policy(
        assignment(Role.ANALYST, RETAIL),
        assignment(Role.ADMIN, RETAIL, expires_in=3600),
    )
    checker = rechecker(repo(doc))
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.propose") is True
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "config.manage") is True


async def test_expired_assignment_denies() -> None:
    clock = Clock()
    checker = rechecker(
        repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL, expires_in=60))), clock=clock
    )
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True
    clock.now = T0 + timedelta(seconds=60)
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False


async def test_assignment_is_clipped_to_domain_memberships() -> None:
    doc = policy(assignment(Role.DOMAIN_STEWARD, RETAIL, HR), memberships=(RETAIL,))
    checker = rechecker(repo(doc))
    assert await checker.check(MAKER, CUSTOMER, HR, "action.execute") is False
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True


async def test_resource_grant_never_confers_a_domain_permission() -> None:
    grant = PolicyGrant(
        grant_id="g-1",
        resource_id=AGENT,
        permissions=("execute",),
        expires_at=T0 + timedelta(hours=1),
        reason="incident review INC-42",
    )
    checker = rechecker(repo(policy(grants=(grant,))))
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False
    assert await checker.check(MAKER, CUSTOMER, AGENT, "action.execute") is False


@pytest.mark.parametrize(
    ("domain", "customer"),
    [
        (OTHER_CUSTOMER, CUSTOMER),
        (GOV_RETAIL, CUSTOMER),
        (RETAIL, "fabrikam"),
        ("commercial:contoso:catalog", CUSTOMER),
    ],
)
async def test_other_cloud_customer_or_malformed_domain_denies(domain: str, customer: str) -> None:
    doc = policy(assignment(Role.DOMAIN_STEWARD, RETAIL))
    repository = repo(doc)
    assert await rechecker(repository).check(MAKER, customer, domain, "action.execute") is False


async def test_unknown_permission_denies() -> None:
    checker = rechecker(repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL))))
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.everything") is False


async def test_missing_head_or_document_denies() -> None:
    doc = policy(assignment(Role.DOMAIN_STEWARD, RETAIL))
    headless = rechecker(repo(doc, head=False))
    assert await headless.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False
    assert await rechecker(repo()).check(MAKER, CUSTOMER, RETAIL, "action.execute") is False


async def test_policy_change_is_seen_on_the_next_check() -> None:
    repository = repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL)))
    checker = rechecker(repository)
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True
    repository.put_principal(policy(assignment(Role.VIEWER, RETAIL)))
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False


# -- revocation --------------------------------------------------------------------------------


async def test_revoked_principal_is_denied_regardless_of_roles() -> None:
    clock = Clock()
    store, checker_rev = revocations(clock)
    repository = repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL)))
    checker = rechecker(repository, revocation=checker_rev, clock=clock)
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True
    await revoke(store, MAKER, T0)
    checker_rev.invalidate_principal(MAKER)
    reads = repository.principal_reads
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False
    assert repository.principal_reads == reads  # revocation decides before the policy read


async def test_revocation_long_ago_still_denies_without_a_token() -> None:
    clock = Clock()
    store, checker_rev = revocations(clock)
    await revoke(store, MAKER, T0 - timedelta(hours=20))
    checker = rechecker(
        repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL))), revocation=checker_rev, clock=clock
    )
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is False


async def test_revocation_store_outage_fails_closed() -> None:
    clock = Clock()
    store, checker_rev = revocations(clock)
    store.fail_with(RuntimeError("cosmos down"))
    checker = rechecker(
        repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL))), revocation=checker_rev, clock=clock
    )
    with pytest.raises(DependencyTransientError):
        await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute")


class _BrokenRevocation:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.mark.parametrize(
    ("answer", "error", "status"),
    [(None, ValueError("boom"), 503), ("yes", None, 502)],
)
async def test_revocation_checker_failure_or_garbage_fails_closed(
    answer: Any, error: Exception | None, status: int
) -> None:
    checker = rechecker(
        repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL))),
        revocation=_BrokenRevocation(answer, error),
    )
    with pytest.raises(DependencyTransientError) as raised:
        await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute")
    assert raised.value.reason == "revocation_unavailable"
    assert raised.value.status == status


def test_revocation_checker_is_required() -> None:
    with pytest.raises(TypeError):
        PolicyPermissionRechecker(
            cloud=CloudName.COMMERCIAL,
            policy_repository=repo(),
            revocation_checker=None,  # type: ignore[arg-type]
        )


# -- fail closed on the policy store ---------------------------------------------------------


async def test_policy_store_outage_fails_closed() -> None:
    repository = repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL)))
    repository.fail_with(RuntimeError("cosmos down"))
    with pytest.raises(DependencyTransientError) as raised:
        await rechecker(repository).check(MAKER, CUSTOMER, RETAIL, "action.execute")
    assert raised.value.reason == "policy_store_unavailable"
    assert raised.value.status == 503


async def test_outage_after_an_allow_is_not_served_from_cache() -> None:
    repository = repo(policy(assignment(Role.DOMAIN_STEWARD, RETAIL)))
    checker = rechecker(repository)
    assert await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute") is True
    repository.fail_with(RuntimeError("cosmos down"))
    with pytest.raises(DependencyTransientError):
        await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute")


async def test_hanging_store_times_out_as_transient() -> None:
    class Hanging(InMemoryPolicyRepository):
        async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
            await asyncio.Event().wait()
            return None

    checker = rechecker(Hanging(), store_timeout_seconds=0.001)
    with pytest.raises(DependencyTransientError) as raised:
        await checker.check(MAKER, CUSTOMER, RETAIL, "action.execute")
    assert raised.value.reason == "policy_store_unavailable"


async def test_document_for_another_principal_is_upstream_invalid() -> None:
    repository = InMemoryPolicyRepository()
    repository.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    stray = policy(assignment(Role.DOMAIN_STEWARD, RETAIL), principal_id=ADMIN)
    repository._principals[(CUSTOMER, MAKER)] = stray  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(DependencyTransientError) as raised:
        await rechecker(repository).check(MAKER, CUSTOMER, RETAIL, "action.execute")
    assert raised.value.status == 502


# -- parity with the API's derived-scope check ---------------------------------------------------


def _claims(clock: Clock) -> VerifiedClaims:
    return VerifiedClaims(
        issuer_kind="entra",
        cloud=CloudName.COMMERCIAL,
        issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
        audience="api://neurosphere-test-api",
        tenant_id=TENANT,
        object_id=OBJECT_ID,
        subject="subject-6c1d2e3f",
        token_version="2.0",  # noqa: S106 - JWT version claim, not a secret
        issued_at=clock.now - timedelta(seconds=60),
        not_before=clock.now - timedelta(seconds=60),
        expires_at=clock.now + timedelta(hours=1),
        identity_type="user",
    )


_PARITY_POLICIES = [
    policy(assignment(Role.DOMAIN_STEWARD, RETAIL)),
    policy(assignment(Role.ANALYST, RETAIL, FINANCE)),
    policy(assignment(Role.DOMAIN_STEWARD, RETAIL, HR), memberships=(RETAIL,)),
    policy(assignment(Role.DOMAIN_STEWARD, RETAIL, expires_in=-1)),
    policy(assignment(Role.VIEWER, FINANCE), assignment(Role.DOMAIN_STEWARD, RETAIL)),
    policy(assignment(Role.ADMIN, RETAIL, expires_in=3600)),
    policy(),
]


@pytest.mark.parametrize("doc", _PARITY_POLICIES)
async def test_decision_matches_permits_on_a_derived_scope(doc: PrincipalPolicy) -> None:
    clock = Clock()
    repository = repo(doc)
    deriver = ScopeDeriver(
        ScopeDerivationConfig(cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER),
        policy_repository=repository,
        pseudonymizer=_PSEUDONYMIZER,
        revocation_checker=NoRevocationCheck(),
        clock=clock.epoch,
    )
    scope = await deriver.from_verified_claims(_claims(clock))
    assert scope.to_contract().principal.principal_id.root == MAKER
    checker = rechecker(repository, clock=clock)
    for domain in (RETAIL, FINANCE, HR):
        for permission in Permission:
            expected = permits(scope, permission, now=clock.now, domain_id=domain)
            got = await checker.check(MAKER, CUSTOMER, domain, permission.value)
            assert got is expected, (domain, permission)


# -- through ActionService ---------------------------------------------------------------------


async def test_action_service_uses_it_to_block_a_revoked_maker() -> None:
    """End to end: a maker revoked after confirmation cannot be handed to the executor."""
    rev_clock = Clock()
    store, checker_rev = revocations(rev_clock)
    maker_doc = policy(assignment(Role.DOMAIN_STEWARD, RETAIL))
    clock = FakeClock()
    checker = PolicyPermissionRechecker(
        cloud=CloudName.COMMERCIAL,
        policy_repository=repo(maker_doc),
        revocation_checker=checker_rev,
        clock=clock,
    )
    auditor = RecordingActionAuditor()
    service = ActionService(
        InMemoryIntentStore(),
        auditor=auditor,
        rechecker=checker,
        execution_control=InMemoryExecutionControl(),
        clock=clock,
    )
    who = caller(MAKER, "p-maker01")
    drafted = await service.draft(who, request(), customer_id=CUSTOMER, domain_id=RETAIL)
    validated = await service.record_validation(drafted.stored.key, who, [passed()])
    presented = await service.present_confirmation(validated.key, who)
    await revoke(store, MAKER, T0)
    bound = presented.intent.confirmation_hash
    assert bound is not None
    with pytest.raises(ForbiddenError):
        await service.confirm(
            presented.key,
            who,
            confirmation_hash=bound.root,
            current_target_version=presented.intent.target_version,
            requires_approval=False,
            advisory=False,
        )
    assert any(e.kind == "denied" for e in auditor.events)
    assert (await service.get(presented.key)).state == "awaiting_confirmation"
